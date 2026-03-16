import asyncio
import logging
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
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
