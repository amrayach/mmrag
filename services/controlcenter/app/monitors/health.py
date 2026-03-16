import asyncio
import logging

import httpx

from .. import config
from ..eventbus import EventBus, Event

logger = logging.getLogger("controlcenter.monitors.health")

# Cached health results: container_name -> {"ok": bool, "detail": str, "ts": float}
_cached_health: dict[str, dict] = {}
_health_lock = asyncio.Lock()


async def get_cached_health() -> dict[str, dict]:
    async with _health_lock:
        return dict(_cached_health)


async def health_monitor(eventbus: EventBus, interval: float = 30.0):
    """Poll health endpoints of all services every interval seconds."""
    prev_ok: dict[str, bool] = {}

    logger.info("Health monitor started (interval=%.0fs)", interval)
    while True:
        try:
            async with httpx.AsyncClient(timeout=config.TIMEOUT_SHORT) as client:
                for container_name, url in config.SERVICE_HEALTH_URLS.items():
                    short = container_name.replace(config.CONTAINER_PREFIX, "")
                    ok = False
                    detail = ""
                    try:
                        resp = await client.get(url)
                        ok = resp.status_code < 400
                        detail = f"status {resp.status_code}"
                    except httpx.ConnectError:
                        detail = "connection refused"
                    except httpx.TimeoutException:
                        detail = "timeout"
                    except Exception as e:
                        detail = str(e)

                    async with _health_lock:
                        _cached_health[container_name] = {
                            "ok": ok,
                            "detail": detail,
                        }

                    was_ok = prev_ok.get(container_name)
                    if was_ok is not None and was_ok != ok:
                        severity = "info" if ok else "warning"
                        msg = f"{short}: health {'recovered' if ok else 'degraded'} ({detail})"
                        eventbus.emit(Event(
                            type="health:change",
                            message=msg,
                            severity=severity,
                            service=short,
                            data={"ok": ok, "detail": detail},
                        ))
                        logger.info(msg)

                    prev_ok[container_name] = ok

        except Exception:
            logger.exception("Health monitor error")

        await asyncio.sleep(interval)
