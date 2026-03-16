import asyncio

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from .. import config, docker_client
from ..eventbus import Event
from ..monitors.container import get_cached_containers
from ..monitors.health import get_cached_health

router = APIRouter(prefix="/api/services", tags=["services"])


@router.get("")
async def list_services():
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


@router.get("/{name}/stats")
async def service_stats(name: str):
    try:
        raw = await docker_client.get_container_stats(name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Parse Docker stats into readable format
    cpu_delta = raw.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0) - \
                raw.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
    system_delta = raw.get("cpu_stats", {}).get("system_cpu_usage", 0) - \
                   raw.get("precpu_stats", {}).get("system_cpu_usage", 0)
    num_cpus = raw.get("cpu_stats", {}).get("online_cpus", 1) or 1
    cpu_pct = (cpu_delta / system_delta * num_cpus * 100) if system_delta > 0 else 0

    mem_usage = raw.get("memory_stats", {}).get("usage", 0)
    mem_limit = raw.get("memory_stats", {}).get("limit", 0)
    mem_pct = (mem_usage / mem_limit * 100) if mem_limit > 0 else 0

    net_rx = 0
    net_tx = 0
    for iface in (raw.get("networks") or {}).values():
        net_rx += iface.get("rx_bytes", 0)
        net_tx += iface.get("tx_bytes", 0)

    return {
        "cpu_percent": round(cpu_pct, 2),
        "memory_usage": mem_usage,
        "memory_limit": mem_limit,
        "memory_percent": round(mem_pct, 2),
        "net_rx_bytes": net_rx,
        "net_tx_bytes": net_tx,
    }


@router.get("/{name}/logs")
async def service_logs(name: str, tail: int = Query(default=100, ge=1, le=5000)):
    """SSE stream of container logs. Falls back to static tail for stopped containers."""
    async def _generate():
        try:
            q = await docker_client.stream_container_logs(name, tail=tail)
            while True:
                line = await asyncio.wait_for(q.get(), timeout=300)
                if line is None:
                    yield {"event": "system", "data": "[Log stream ended]"}
                    break
                yield {"event": "log", "data": line.rstrip("\n")}
        except asyncio.TimeoutError:
            yield {"event": "system", "data": "[Log stream timeout]"}
        except Exception as e:
            # Fallback: static logs for stopped containers
            err_msg = str(e)
            if "not running" in err_msg.lower() or "is not running" in err_msg.lower():
                try:
                    static = await docker_client.get_container_logs(name, tail=tail)
                    for line in static.splitlines():
                        yield {"event": "log", "data": line}
                    yield {"event": "system", "data": "[Container is not running]"}
                except Exception as e2:
                    yield {"event": "system", "data": f"[Error reading logs: {e2}]"}
            else:
                yield {"event": "system", "data": f"[Log stream error: {e}]"}

    return EventSourceResponse(_generate())


@router.get("/{name}/env")
async def service_env(name: str):
    try:
        return await docker_client.get_container_env(name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{name}/start")
async def service_start(name: str):
    try:
        result = await docker_client.start_container(name)
        from ..main import eventbus
        eventbus.emit(Event(
            type="container:state",
            message=f"{name}: started via UI",
            severity="info",
            service=name,
        ))
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{name}/stop")
async def service_stop(name: str, confirm: bool = Query(default=False)):
    full_name = docker_client._validate_name(name)
    if full_name in config.CRITICAL_CONTAINERS and not confirm:
        raise HTTPException(
            status_code=400,
            detail=f"Stopping {name} requires ?confirm=true (critical service)",
        )
    try:
        result = await docker_client.stop_container(name)
        from ..main import eventbus
        eventbus.emit(Event(
            type="container:state",
            message=f"{name}: stopped via UI",
            severity="warning",
            service=name,
        ))
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{name}/restart")
async def service_restart(name: str, confirm: bool = Query(default=False)):
    full_name = docker_client._validate_name(name)
    if full_name in config.CRITICAL_CONTAINERS and not confirm:
        raise HTTPException(
            status_code=400,
            detail=f"Restarting {name} requires ?confirm=true (critical service)",
        )
    try:
        result = await docker_client.restart_container(name)
        from ..main import eventbus
        eventbus.emit(Event(
            type="container:state",
            message=f"{name}: restarted via UI",
            severity="info",
            service=name,
        ))
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
