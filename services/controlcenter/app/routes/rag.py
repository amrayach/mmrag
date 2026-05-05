import json
import logging
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import config

logger = logging.getLogger("controlcenter.routes.rag")

router = APIRouter(prefix="/api/rag", tags=["rag"])


class RagMessage(BaseModel):
    role: str
    content: str


class RagQuery(BaseModel):
    messages: list[RagMessage]
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 800


@router.post("/query")
async def rag_query(query: RagQuery, request: Request):
    """SSE stream: proxy through rag-gateway (direct context + Ollama streaming)."""
    return StreamingResponse(
        _rag_stream(query, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/models")
async def rag_models():
    """Proxy to rag-gateway /v1/models."""
    async with httpx.AsyncClient(timeout=config.TIMEOUT_SHORT) as client:
        resp = await client.get(f"{config.RAG_GATEWAY_URL}/v1/models")
        data = resp.json()
        if isinstance(data, dict):
            data["default_model"] = config.OLLAMA_TEXT_MODEL
        return data


def _sse(event: str, data) -> str:
    payload = json.dumps(data) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {payload}\n\n"


async def _rag_stream(query: RagQuery, request: Request):
    """Proxy streaming through rag-gateway's OpenAI-compatible endpoint."""
    t0 = time.monotonic()
    model = query.model or config.OLLAMA_TEXT_MODEL
    total_tokens = 0

    payload = {
        "messages": [m.model_dump() for m in query.messages],
        "model": model,
        "temperature": query.temperature,
        "max_tokens": query.max_tokens,
        "stream": True,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{config.RAG_GATEWAY_URL}/v1/chat/completions",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if await request.is_disconnected():
                        logger.info("Client disconnected, stopping stream")
                        break
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        total_tokens += 1
                        yield _sse("token", {"content": content})
    except httpx.TimeoutException:
        logger.warning("rag-gateway stream timeout")
        yield _sse("error", {"message": "RAG gateway response timeout"})
    except Exception as e:
        logger.error("rag-gateway stream error: %s", e)
        yield _sse("error", {"message": f"RAG gateway stream error: {e}"})

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    yield _sse("done", {"total_tokens": total_tokens, "elapsed_ms": elapsed_ms})
