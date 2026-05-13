import asyncio
import logging
import math
import re
from contextlib import asynccontextmanager
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from . import config, db, docker_client
from .eventbus import EventBus, Event
from .monitors.container import container_monitor
from .monitors.health import health_monitor
from .monitors.ingestion import ingestion_monitor
from .monitors.models import model_monitor
from .routes import dashboard, services, timeline, ingestion, demo, rag, docs, system, data_explorer

# ---------------------------------------------------------------------------
# Logging (structured JSON)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("controlcenter")

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
eventbus = EventBus(maxlen=1000)

# Background monitor tasks
_monitor_tasks: list[asyncio.Task] = []

_DEMO_CODE_CREATE_FIELDS = {"ttl_hours", "max_redemptions", "label", "notes", "created_by"}


def _demo_admin_disabled_response():
    return JSONResponse(
        status_code=503,
        content={
            "error": "admin_disabled",
            "message": "Demo access administration is disabled because DEMO_SITE_ADMIN_TOKEN is not configured.",
        },
    )


def _with_demo_public_url(data):
    public_url = config.DEMO_PUBLIC_URL.strip()
    if not public_url or not isinstance(data, dict):
        return data
    return {**data, "demo_public_url": public_url}


def _invalid_demo_access_request(message: str):
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_request", "message": message},
    )


def _is_positive_number(value) -> bool:
    if isinstance(value, bool):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed) and parsed > 0


def _validate_demo_code_payload(body):
    if not isinstance(body, dict):
        return None, _invalid_demo_access_request("JSON body must be an object.")

    payload = {key: body[key] for key in _DEMO_CODE_CREATE_FIELDS if key in body}

    ttl_hours = payload.get("ttl_hours")
    if ttl_hours is not None and not _is_positive_number(ttl_hours):
        return None, _invalid_demo_access_request("ttl_hours must be a positive number.")

    max_redemptions = payload.get("max_redemptions")
    if max_redemptions is not None and not _is_positive_number(max_redemptions):
        return None, _invalid_demo_access_request("max_redemptions must be a positive number.")

    for key in ("label", "notes", "created_by"):
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            return None, _invalid_demo_access_request(f"{key} must be a string.")

    return payload, None


async def _proxy_demo_admin_request(method: str, path: str, json_body=None):
    token = config.DEMO_SITE_ADMIN_TOKEN.strip()
    if not token:
        return _demo_admin_disabled_response()

    url = f"{config.DEMO_SITE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=config.TIMEOUT_STANDARD) as client:
            resp = await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=json_body,
            )
    except httpx.HTTPError:
        logger.warning("demo-site admin proxy request failed", exc_info=True)
        return JSONResponse(
            status_code=502,
            content={
                "error": "demo_site_unavailable",
                "message": "Demo-site admin API is unavailable.",
            },
        )

    try:
        data = resp.json()
    except ValueError:
        logger.warning("demo-site admin proxy returned non-JSON response: HTTP %s", resp.status_code)
        return JSONResponse(
            status_code=502,
            content={
                "error": "demo_site_bad_response",
                "message": "Demo-site admin API returned a non-JSON response.",
            },
        )

    return JSONResponse(status_code=resp.status_code, content=_with_demo_public_url(data))


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.init_pool()
    docker_client.init_client()

    # Start background monitors
    _monitor_tasks.extend([
        asyncio.create_task(container_monitor(eventbus, interval=10.0)),
        asyncio.create_task(health_monitor(eventbus, interval=30.0)),
        asyncio.create_task(ingestion_monitor(eventbus, active_interval=10.0, idle_interval=30.0)),
        asyncio.create_task(model_monitor(eventbus, interval=60.0)),
    ])

    eventbus.emit(Event(
        type="system:info",
        message="Control Center started",
        severity="info",
        service="controlcenter",
    ))
    logger.info("controlcenter v0.6.0 started (%d monitors)", len(_monitor_tasks))
    yield

    # Shutdown: cancel monitors
    for task in _monitor_tasks:
        task.cancel()
    await asyncio.gather(*_monitor_tasks, return_exceptions=True)
    _monitor_tasks.clear()

    docker_client.close_client()
    await db.close_pool()
    logger.info("controlcenter shutting down")


app = FastAPI(title="controlcenter", version="0.6.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Include route routers
# ---------------------------------------------------------------------------
app.include_router(dashboard.router)
app.include_router(services.router)
app.include_router(timeline.router)
app.include_router(ingestion.router)
app.include_router(demo.router)
app.include_router(rag.router)
app.include_router(docs.router)
app.include_router(system.router)
app.include_router(data_explorer.router)


# ---------------------------------------------------------------------------
# Asset proxy (streaming, security-hardened)
# ---------------------------------------------------------------------------
_ASSET_PATH_RE = re.compile(r'^[a-zA-Z0-9_/.-]+\.(jpg|jpeg|png|webp|gif)$')


@app.get("/api/assets/{path:path}")
async def proxy_assets(path: str):
    if not _ASSET_PATH_RE.match(path):
        raise HTTPException(status_code=400, detail="Invalid asset path")
    url = f"{config.ASSETS_INTERNAL_URL}/{path}"
    client = httpx.AsyncClient(timeout=10)
    try:
        req = client.build_request("GET", url)
        resp = await client.send(req, stream=True)
        if resp.status_code != 200:
            await resp.aclose()
            await client.aclose()
            raise HTTPException(status_code=resp.status_code, detail="Asset not found")
        cl = int(resp.headers.get("content-length", "0"))
        if cl > 20_000_000:
            await resp.aclose()
            await client.aclose()
            raise HTTPException(status_code=413, detail="Asset too large")

        async def _cleanup():
            await resp.aclose()
            await client.aclose()

        return StreamingResponse(
            resp.aiter_bytes(),
            media_type=resp.headers.get("content-type", "image/jpeg"),
            background=BackgroundTask(_cleanup),
        )
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Asset service unavailable")


# ---------------------------------------------------------------------------
# Demo access proxy (server-side admin token only)
# ---------------------------------------------------------------------------
@app.get("/api/demo-access/codes")
async def list_demo_access_codes():
    return await _proxy_demo_admin_request("GET", "/api/admin/codes")


@app.post("/api/demo-access/codes")
async def create_demo_access_code(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return _invalid_demo_access_request("Request body must be valid JSON.")

    payload, error = _validate_demo_code_payload(body)
    if error is not None:
        return error

    return await _proxy_demo_admin_request("POST", "/api/admin/codes", json_body=payload)


@app.post("/api/demo-access/codes/{code}/revoke")
async def revoke_demo_access_code(code: str):
    quoted_code = quote(code, safe="")
    return await _proxy_demo_admin_request("POST", f"/api/admin/codes/{quoted_code}/revoke")


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/health/ready")
async def health_ready():
    checks = {}

    # DB check
    try:
        await db.fetch_one("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = str(e)

    # Docker check
    try:
        ok = await docker_client.docker_ping()
        checks["docker"] = "ok" if ok else "ping failed"
    except Exception as e:
        checks["docker"] = str(e)

    ok = all(v == "ok" for v in checks.values())
    return {"ok": ok, "checks": checks}


# ---------------------------------------------------------------------------
# SPA fallback — serve index.html for root
# ---------------------------------------------------------------------------
@app.get("/")
async def spa_root():
    return FileResponse("/app/app/static/index.html")


# ---------------------------------------------------------------------------
# Static files mount (after routes to avoid shadowing API)
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="/app/app/static"), name="static")
