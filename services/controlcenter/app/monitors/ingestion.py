import asyncio
import logging

import httpx

from .. import config
from ..eventbus import EventBus, Event

logger = logging.getLogger("controlcenter.monitors.ingestion")

# Cached ingestion status
_cached_pdf_status: dict = {}
_cached_rss_status: dict = {}
_status_lock = asyncio.Lock()


async def get_cached_ingestion() -> dict:
    async with _status_lock:
        return {"pdf": dict(_cached_pdf_status), "rss": dict(_cached_rss_status)}


async def ingestion_monitor(eventbus: EventBus, active_interval: float = 10.0, idle_interval: float = 30.0):
    """Poll pdf-ingest + rss-ingest /ingest/status. 10s when active, 30s idle."""
    prev_pdf_active = 0
    prev_rss_active = False

    logger.info("Ingestion monitor started (active=%.0fs, idle=%.0fs)", active_interval, idle_interval)
    while True:
        is_active = False
        try:
            async with httpx.AsyncClient(timeout=config.TIMEOUT_SHORT) as client:
                # PDF ingest status
                try:
                    resp = await client.get(f"{config.PDF_INGEST_URL}/ingest/status")
                    if resp.status_code < 400:
                        pdf_data = resp.json()
                        async with _status_lock:
                            _cached_pdf_status.clear()
                            _cached_pdf_status.update(pdf_data)

                        active_docs = pdf_data.get("active_docs", 0)
                        if active_docs > 0:
                            is_active = True
                        if active_docs > 0 and prev_pdf_active == 0:
                            eventbus.emit(Event(
                                type="ingest:progress",
                                message=f"PDF ingestion active ({active_docs} docs)",
                                severity="info",
                                service="pdf-ingest",
                                data=pdf_data,
                            ))
                        elif active_docs == 0 and prev_pdf_active > 0:
                            eventbus.emit(Event(
                                type="ingest:complete",
                                message="PDF ingestion idle",
                                severity="info",
                                service="pdf-ingest",
                                data=pdf_data,
                            ))
                        prev_pdf_active = active_docs
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass

                # RSS ingest status
                try:
                    resp = await client.get(f"{config.RSS_INGEST_URL}/ingest/status")
                    if resp.status_code < 400:
                        rss_data = resp.json()
                        async with _status_lock:
                            _cached_rss_status.clear()
                            _cached_rss_status.update(rss_data)

                        rss_active = rss_data.get("is_running", False)
                        if rss_active:
                            is_active = True
                        if rss_active and not prev_rss_active:
                            eventbus.emit(Event(
                                type="ingest:progress",
                                message="RSS ingestion started",
                                severity="info",
                                service="rss-ingest",
                                data=rss_data,
                            ))
                        elif not rss_active and prev_rss_active:
                            eventbus.emit(Event(
                                type="ingest:complete",
                                message="RSS ingestion completed",
                                severity="info",
                                service="rss-ingest",
                                data=rss_data,
                            ))
                        prev_rss_active = rss_active
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass

        except Exception:
            logger.exception("Ingestion monitor error")

        await asyncio.sleep(active_interval if is_active else idle_interval)
