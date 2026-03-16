from fastapi import APIRouter

from .. import db
from ..monitors.container import get_cached_containers
from ..monitors.health import get_cached_health

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
