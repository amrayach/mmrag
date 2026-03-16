import asyncio

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def get_events(
    service: str = Query(default=""),
    severity: str = Query(default=""),
    search: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=500),
):
    from ..main import eventbus
    return eventbus.recent(limit=limit, service=service, severity=severity, search=search)


@router.get("/stream")
async def event_stream():
    """Single SSE stream of all events. Client-side filtering."""
    from ..main import eventbus

    sub_id, q = eventbus.subscribe()

    async def _generate():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    yield {"event": "event", "data": event.to_dict(), "id": event.id}
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield {"event": "ping", "data": ""}
        except asyncio.CancelledError:
            pass
        finally:
            eventbus.unsubscribe(sub_id)

    return EventSourceResponse(_generate())
