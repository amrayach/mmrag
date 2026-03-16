import asyncio
import logging

import httpx

from .. import config
from ..eventbus import EventBus, Event

logger = logging.getLogger("controlcenter.monitors.models")

# Cached model state
_cached_models: list[dict] = []
_models_lock = asyncio.Lock()


async def get_cached_models() -> list[dict]:
    async with _models_lock:
        return list(_cached_models)


async def model_monitor(eventbus: EventBus, interval: float = 60.0):
    """Poll Ollama /api/ps every interval seconds. Detect model load/unload."""
    prev_loaded: set[str] = set()

    logger.info("Model monitor started (interval=%.0fs)", interval)
    while True:
        try:
            async with httpx.AsyncClient(timeout=config.TIMEOUT_SHORT) as client:
                resp = await client.get(f"{config.OLLAMA_BASE_URL}/api/ps")
                if resp.status_code < 400:
                    data = resp.json()
                    models = data.get("models", [])

                    async with _models_lock:
                        _cached_models.clear()
                        _cached_models.extend(models)

                    current_loaded = {m.get("name", "") for m in models}

                    # Detect newly loaded
                    for name in current_loaded - prev_loaded:
                        if prev_loaded:  # skip first poll
                            vram = 0
                            for m in models:
                                if m.get("name") == name:
                                    vram = m.get("size_vram", 0)
                                    break
                            eventbus.emit(Event(
                                type="model:loaded",
                                message=f"Model loaded: {name}",
                                severity="info",
                                service="ollama",
                                data={"model": name, "vram": vram},
                            ))
                            logger.info("Model loaded: %s", name)

                    # Detect unloaded
                    for name in prev_loaded - current_loaded:
                        eventbus.emit(Event(
                            type="model:unloaded",
                            message=f"Model unloaded: {name}",
                            severity="warning",
                            service="ollama",
                            data={"model": name},
                        ))
                        logger.info("Model unloaded: %s", name)

                    prev_loaded = current_loaded

        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        except Exception:
            logger.exception("Model monitor error")

        await asyncio.sleep(interval)
