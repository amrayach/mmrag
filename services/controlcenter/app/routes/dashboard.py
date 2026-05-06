from fastapi import APIRouter

from .. import config, db
from ..monitors.container import get_cached_containers
from ..monitors.health import get_cached_health
from ..monitors.models import get_cached_models

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/metrics")
async def dashboard_metrics():
    containers = await get_cached_containers()
    running = sum(1 for c in containers if c["state"] == "running")
    counts = await db.get_doc_counts()
    return {
        "containers_up": running,
        "containers_total": len(containers),
        **counts,
    }


@router.get("/runtime")
async def dashboard_runtime():
    """Current demo baseline shown on the Dashboard page."""
    loaded_models = await get_cached_models()
    loaded_names = {
        m.get("name") or m.get("model", "")
        for m in loaded_models
        if m.get("name") or m.get("model")
    }

    def loaded(expected: str):
        if not loaded_models:
            return None
        return any(
            name == expected or name.startswith(f"{expected}:")
            for name in loaded_names
        )

    return {
        "ollama_image": "ollama/ollama:0.23.1",
        "gateway_version": "0.7.0",
        "readiness": {"pass": 18, "fail": 0, "warn": 1},
        "models": [
            {
                "role": "Text generation",
                "name": config.OLLAMA_TEXT_MODEL,
                "loaded": loaded(config.OLLAMA_TEXT_MODEL),
                "note": "Production default; MoE, 4B active params per token",
            },
            {
                "role": "Embeddings",
                "name": config.OLLAMA_EMBED_MODEL,
                "loaded": loaded(config.OLLAMA_EMBED_MODEL),
                "note": "Multilingual, 1024-dimensional vectors",
            },
            {
                "role": "Vision captions",
                "name": config.OLLAMA_VISION_MODEL,
                "loaded": loaded(config.OLLAMA_VISION_MODEL),
                "note": "Image captioning during ingestion",
            },
        ],
        "eval": {
            "label": "gemma4:26b full eval",
            "avg_ttft_ms": 1084,
            "avg_total_s": 7.0,
            "baseline_total_s": 9.8,
            "run_dir": "data/eval/runs/20260506_015332__gemma4_26b/",
        },
        "pdf": {
            "chunks": 1648,
            "bbox_chunks": 1648,
            "bmw_unembedded": 486,
        },
    }


@router.get("/topology")
async def dashboard_topology():
    containers = await get_cached_containers()
    health = await get_cached_health()
    result = []
    for c in containers:
        h = health.get(c["name"], {})
        result.append({
            **c,
            "health_ok": h.get("ok"),
            "health_detail": h.get("detail", ""),
        })
    return result


@router.get("/graph")
async def dashboard_graph():
    """Service graph with live container status merged in."""
    from .system import service_graph as _sg
    graph_data = await _sg()
    containers = await get_cached_containers()
    health = await get_cached_health()

    # Build lookup: short_name -> {state, health_ok}
    status_map = {}
    for c in containers:
        short = c.get("short_name", c["name"])
        h = health.get(c["name"], {})
        status_map[short] = {
            "state": c["state"],
            "health_ok": h.get("ok"),
        }

    # Merge status into nodes
    for node in graph_data["nodes"]:
        st = status_map.get(node["id"], {})
        node["state"] = st.get("state", "unknown")
        node["health_ok"] = st.get("health_ok")

    return graph_data


@router.get("/recent")
async def dashboard_recent():
    from ..main import eventbus
    return eventbus.recent(limit=10)
