import logging

import httpx
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from .. import config, docker_client
from ..eventbus import Event
from ..monitors.models import get_cached_models
from ..monitors.container import get_cached_containers

logger = logging.getLogger("controlcenter.routes.demo")

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/status")
async def demo_status():
    """Check if demo mode is active: rss-ingest stopped + models loaded."""
    containers = await get_cached_containers()
    rss = next((c for c in containers if c["short_name"] == "rss_ingest"), None)
    rss_stopped = rss is None or rss["state"] != "running"

    models = await get_cached_models()
    loaded_names = {m.get("name", "") for m in models}

    expected = {config.OLLAMA_TEXT_MODEL, config.OLLAMA_VISION_MODEL, config.OLLAMA_EMBED_MODEL}
    all_loaded = expected.issubset(loaded_names)

    return {
        "demo_active": rss_stopped,
        "rss_ingest_state": rss["state"] if rss else "not found",
        "models_loaded": list(loaded_names),
        "models_expected": list(expected),
        "all_models_loaded": all_loaded,
    }


@router.post("/start")
async def demo_start():
    """Activate demo mode: stop rss-ingest, prewarm 3 models, verify health."""
    from ..main import eventbus
    steps = []

    # Step 1: Stop rss-ingest
    try:
        result = await docker_client.stop_container("rss_ingest")
        steps.append({"step": "stop_rss_ingest", "status": "ok", "detail": result})
    except Exception as e:
        steps.append({"step": "stop_rss_ingest", "status": "error", "detail": str(e)})

    # Step 2: Prewarm models
    async with httpx.AsyncClient(timeout=config.TIMEOUT_LONG) as client:
        for model_name, endpoint, payload in [
            (config.OLLAMA_VISION_MODEL, "/api/generate",
             {"model": config.OLLAMA_VISION_MODEL, "prompt": "Describe this test.",
              "keep_alive": "1h", "stream": False}),
            (config.OLLAMA_EMBED_MODEL, "/api/embeddings",
             {"model": config.OLLAMA_EMBED_MODEL, "prompt": "test", "keep_alive": "1h"}),
            (config.OLLAMA_TEXT_MODEL, "/api/generate",
             {"model": config.OLLAMA_TEXT_MODEL, "prompt": "Sag kurz Hallo auf Deutsch.",
              "keep_alive": "1h", "stream": False}),
        ]:
            try:
                resp = await client.post(f"{config.OLLAMA_BASE_URL}{endpoint}", json=payload)
                steps.append({"step": f"prewarm_{model_name}", "status": "ok",
                              "detail": f"HTTP {resp.status_code}"})
            except Exception as e:
                steps.append({"step": f"prewarm_{model_name}", "status": "error",
                              "detail": str(e)})

    # Step 3: Health check
    async with httpx.AsyncClient(timeout=config.TIMEOUT_SHORT) as client:
        for name, url in [("rag-gateway", f"{config.RAG_GATEWAY_URL}/health"),
                          ("n8n", f"{config.N8N_BASE_URL}/healthz")]:
            try:
                resp = await client.get(url)
                steps.append({"step": f"health_{name}", "status": "ok",
                              "detail": f"HTTP {resp.status_code}"})
            except Exception as e:
                steps.append({"step": f"health_{name}", "status": "error",
                              "detail": str(e)})

    eventbus.emit(Event(
        type="demo:toggle",
        message="Demo mode activated",
        severity="info",
        service="demo",
        data={"action": "start"},
    ))

    all_ok = all(s["status"] == "ok" for s in steps)
    return {"demo_active": True, "all_ok": all_ok, "steps": steps}


@router.post("/stop")
async def demo_stop():
    """Deactivate demo mode: start rss-ingest."""
    from ..main import eventbus
    try:
        result = await docker_client.start_container("rss_ingest")
        eventbus.emit(Event(
            type="demo:toggle",
            message="Demo mode deactivated",
            severity="info",
            service="demo",
            data={"action": "stop"},
        ))
        return {"demo_active": False, "result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/readiness")
async def demo_readiness():
    """SSE stream: 15-point readiness checklist (reimplements demo_readiness_check.sh)."""
    async def _generate():
        async with httpx.AsyncClient(timeout=config.TIMEOUT_SHORT) as short_client:
            # 1. Containers
            containers = await get_cached_containers()
            running = [c for c in containers if c["state"] == "running"]
            total = len(containers)
            n_running = len(running)
            yield _check(1, "Docker containers",
                         f"{n_running}/{total} running",
                         "pass" if n_running >= 10 else "fail")

            # 2. Ollama responds
            try:
                resp = await short_client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
                models_data = resp.json()
                model_names = [m.get("name", "") for m in models_data.get("models", [])]
                yield _check(2, "Ollama responds", f"{len(model_names)} models available", "pass")
            except Exception as e:
                model_names = []
                yield _check(2, "Ollama responds", str(e), "fail")

            # 3-5. Model checks
            for i, model in enumerate([config.OLLAMA_TEXT_MODEL, config.OLLAMA_EMBED_MODEL,
                                       config.OLLAMA_VISION_MODEL], start=3):
                found = any(model in m for m in model_names)
                yield _check(i, f"Model: {model}",
                             "present" if found else "missing",
                             "pass" if found else "fail")

            # 6. n8n chat webhook
            try:
                resp = await short_client.post(
                    f"{config.N8N_BASE_URL}/webhook/rag-chat",
                    json={"messages": []},
                )
                ok = resp.status_code != 404
                yield _check(6, "Chat Brain webhook",
                             f"HTTP {resp.status_code}",
                             "pass" if ok else "fail")
            except Exception as e:
                yield _check(6, "Chat Brain webhook", str(e), "fail")

            # 7. n8n ingest webhook
            try:
                resp = await short_client.post(f"{config.N8N_BASE_URL}/webhook/ingest-now")
                ok = resp.status_code != 404
                yield _check(7, "Ingestion Factory webhook",
                             f"HTTP {resp.status_code}",
                             "pass" if ok else "fail")
            except Exception as e:
                yield _check(7, "Ingestion Factory webhook", str(e), "fail")

            # 8. RSS ingest webhook
            try:
                resp = await short_client.post(f"{config.N8N_BASE_URL}/webhook/rss-ingest-now")
                ok = resp.status_code != 404
                yield _check(8, "RSS Ingestion webhook",
                             f"HTTP {resp.status_code}",
                             "pass" if ok else "warn" if resp.status_code == 404 else "pass")
            except Exception as e:
                yield _check(8, "RSS Ingestion webhook", str(e), "warn")

        # 9. n8n context pipeline (longer timeout)
        async with httpx.AsyncClient(timeout=120) as long_client:
            try:
                resp = await long_client.post(
                    f"{config.N8N_BASE_URL}/webhook/rag-chat",
                    json={"messages": [{"role": "user", "content": "Antworte nur mit OK."}]},
                )
                data = resp.json()
                has_body = "chatRequestBody" in data
                yield _check(9, "Context pipeline",
                             "chatRequestBody present" if has_body else "missing chatRequestBody",
                             "pass" if has_body else "fail")
            except Exception as e:
                yield _check(9, "Context pipeline", str(e), "fail")

        async with httpx.AsyncClient(timeout=config.TIMEOUT_SHORT) as short_client:
            # 10. RAG Gateway SSE
            try:
                resp = await short_client.get(f"{config.RAG_GATEWAY_URL}/health")
                yield _check(10, "RAG Gateway health",
                             f"HTTP {resp.status_code}",
                             "pass" if resp.status_code == 200 else "fail")
            except Exception as e:
                yield _check(10, "RAG Gateway health", str(e), "fail")

            # 11. Demo mode (rss-ingest stopped)
            rss = next((c for c in containers if c["short_name"] == "rss_ingest"), None)
            rss_running = rss and rss["state"] == "running"
            yield _check(11, "Demo mode (rss-ingest)",
                         "running (GPU contention possible)" if rss_running else "stopped (GPU freed)",
                         "warn" if rss_running else "pass")

            # 12. Database
            from .. import db
            try:
                row = await db.fetch_one("SELECT COUNT(*) FROM rag_docs")
                doc_count = row[0] if row else 0
                yield _check(12, "Database documents",
                             f"{doc_count} docs",
                             "pass" if doc_count > 0 else "warn")
            except Exception as e:
                yield _check(12, "Database documents", str(e), "fail")

            # 13. Database chunks
            try:
                row = await db.fetch_one("SELECT COUNT(*) FROM rag_chunks")
                chunk_count = row[0] if row else 0
                yield _check(13, "Database chunks",
                             f"{chunk_count} chunks",
                             "pass" if chunk_count > 0 else "warn")
            except Exception as e:
                yield _check(13, "Database chunks", str(e), "fail")

            # 14. Models loaded in memory
            models = await get_cached_models()
            loaded = {m.get("name", "") for m in models}
            expected = {config.OLLAMA_TEXT_MODEL, config.OLLAMA_VISION_MODEL, config.OLLAMA_EMBED_MODEL}
            missing = expected - loaded
            yield _check(14, "Models loaded in VRAM",
                         f"{len(loaded)}/3 loaded" + (f" (missing: {', '.join(missing)})" if missing else ""),
                         "pass" if not missing else "warn")

            # 15. Tailscale URLs
            if config.TAILNET_HOST:
                yield _check(15, "Tailscale host configured",
                             config.TAILNET_HOST, "pass")
            else:
                yield _check(15, "Tailscale host configured",
                             "TAILNET_HOST not set", "warn")

        # Summary
        yield {"event": "done", "data": ""}

    return EventSourceResponse(_generate())


def _check(num: int, name: str, detail: str, status: str) -> dict:
    return {
        "event": "check",
        "data": {
            "num": num,
            "name": name,
            "detail": detail,
            "status": status,
        },
    }


@router.post("/prewarm")
async def prewarm():
    """Prewarm all 3 Ollama models with 1h keep_alive."""
    results = []
    async with httpx.AsyncClient(timeout=config.TIMEOUT_LONG) as client:
        for model_name, endpoint, payload in [
            (config.OLLAMA_VISION_MODEL, "/api/generate",
             {"model": config.OLLAMA_VISION_MODEL, "prompt": "Describe this test.",
              "keep_alive": "1h", "stream": False}),
            (config.OLLAMA_EMBED_MODEL, "/api/embeddings",
             {"model": config.OLLAMA_EMBED_MODEL, "prompt": "test", "keep_alive": "1h"}),
            (config.OLLAMA_TEXT_MODEL, "/api/generate",
             {"model": config.OLLAMA_TEXT_MODEL, "prompt": "Sag kurz Hallo auf Deutsch.",
              "keep_alive": "1h", "stream": False}),
        ]:
            try:
                resp = await client.post(f"{config.OLLAMA_BASE_URL}{endpoint}", json=payload)
                results.append({"model": model_name, "status": "ok", "http": resp.status_code})
            except Exception as e:
                results.append({"model": model_name, "status": "error", "detail": str(e)})
    return {"results": results}


@router.get("/models")
async def demo_models():
    """Proxy to Ollama /api/ps — shows loaded/unloaded state + VRAM."""
    async with httpx.AsyncClient(timeout=config.TIMEOUT_SHORT) as client:
        try:
            resp = await client.get(f"{config.OLLAMA_BASE_URL}/api/ps")
            data = resp.json()
            models = data.get("models", [])

            expected = [config.OLLAMA_TEXT_MODEL, config.OLLAMA_VISION_MODEL, config.OLLAMA_EMBED_MODEL]
            loaded_names = {m.get("name", "") for m in models}

            result = []
            for name in expected:
                loaded = name in loaded_names
                model_info = next((m for m in models if m.get("name") == name), {})
                result.append({
                    "name": name,
                    "loaded": loaded,
                    "size_vram": model_info.get("size_vram", 0),
                    "size": model_info.get("size", 0),
                    "expires_at": model_info.get("expires_at", ""),
                })

            return {"models": result, "total_vram": sum(m.get("size_vram", 0) for m in models)}
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Ollama unavailable")


@router.get("/tailscale-urls")
async def tailscale_urls():
    """Static config of Tailscale serve URLs."""
    host = config.TAILNET_HOST
    if not host:
        return {"configured": False, "urls": []}

    urls = []
    labels = {
        "ammer_mmragv2_n8n": "n8n",
        "ammer_mmragv2_openwebui": "Chat (OpenWebUI)",
        "ammer_mmragv2_filebrowser": "File Browser",
        "ammer_mmragv2_adminer": "Adminer (DB)",
        "ammer_mmragv2_assets": "Asset Gallery",
        "ammer_mmragv2_controlcenter": "Control Center",
    }
    for container_name, port in config.TAILSCALE_PORT_MAP.items():
        urls.append({
            "label": labels.get(container_name, container_name),
            "url": f"https://{host}:{port}",
            "port": port,
        })

    return {"configured": True, "host": host, "urls": urls}
