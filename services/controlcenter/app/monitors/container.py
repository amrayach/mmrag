import asyncio
import logging

from .. import docker_client
from ..eventbus import EventBus, Event

logger = logging.getLogger("controlcenter.monitors.container")

# Cached container list for API routes
_cached_containers: list[dict] = []
_cache_lock = asyncio.Lock()


async def get_cached_containers() -> list[dict]:
    async with _cache_lock:
        return list(_cached_containers)


async def container_monitor(eventbus: EventBus, interval: float = 10.0):
    """Poll Docker SDK every interval seconds, detect state changes, cache container list."""
    global _cached_containers
    prev_states: dict[str, tuple[str, str]] = {}  # name -> (state, health)

    logger.info("Container monitor started (interval=%.0fs)", interval)
    while True:
        try:
            containers = await docker_client.list_containers()
            async with _cache_lock:
                _cached_containers = containers

            current_states: dict[str, tuple[str, str]] = {}
            for c in containers:
                name = c["name"]
                state = c["state"]
                health = c["health"]
                current_states[name] = (state, health)

                prev = prev_states.get(name)
                if prev is None:
                    continue  # first poll, no change to report
                prev_state, prev_health = prev

                if state != prev_state or health != prev_health:
                    short = c["short_name"]
                    old_label = f"{prev_state}+{prev_health}"
                    new_label = f"{state}+{health}"
                    severity = "info"
                    if state != "running":
                        severity = "warning"
                    if prev_state == "running" and state != "running":
                        severity = "error"

                    eventbus.emit(Event(
                        type="container:state",
                        message=f"{short}: {old_label} -> {new_label}",
                        severity=severity,
                        service=short,
                        data={"old_state": prev_state, "old_health": prev_health,
                              "new_state": state, "new_health": health},
                    ))
                    logger.info("Container %s: %s -> %s", short, old_label, new_label)

            # Detect removed containers
            for name in set(prev_states) - set(current_states):
                short = name.replace("ammer_mmragv2_", "")
                eventbus.emit(Event(
                    type="container:state",
                    message=f"{short}: removed",
                    severity="warning",
                    service=short,
                ))

            prev_states = current_states

        except Exception:
            logger.exception("Container monitor error")

        await asyncio.sleep(interval)
