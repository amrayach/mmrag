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
    """SSE stream: n8n context + Ollama token streaming with cancellation."""
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
        return resp.json()


def _sse(event: str, data) -> str:
    payload = json.dumps(data) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {payload}\n\n"


async def _rag_stream(query: RagQuery, request: Request):
    t0 = time.monotonic()
    model = query.model or config.OLLAMA_TEXT_MODEL
    total_tokens = 0

    # Step 1: Get context from n8n Chat Brain webhook
    n8n_url = config.N8N_CHAT_WEBHOOK_URL
    payload = {
        "query": query.messages[-1].content if query.messages else "",
        "messages": [m.model_dump() for m in query.messages],
        "model": model,
        "temperature": query.temperature,
        "max_tokens": query.max_tokens,
    }

    try:
        async with httpx.AsyncClient(timeout=config.TIMEOUT_N8N_WEBHOOK) as client:
            resp = await client.post(n8n_url, json=payload)
            resp.raise_for_status()
            ctx = resp.json()
    except httpx.TimeoutException:
        yield _sse("error", {"message": "n8n context timeout"})
        yield _sse("done", {"total_tokens": 0, "elapsed_ms": 0})
        return
    except Exception as e:
        logger.error("n8n context error: %s", e)
        yield _sse("error", {"message": f"n8n context error: {e}"})
        yield _sse("done", {"total_tokens": 0, "elapsed_ms": 0})
        return

    chat_body = ctx.get("chatRequestBody", {})
    image_objects = ctx.get("imageObjects", [])
    sources = ctx.get("sources", [])

    # Emit context event (debug: assembled prompt)
    yield _sse("context", {
        "chatRequestBody": chat_body,
        "imageObjects": image_objects,
        "sources": sources,
    })

    if await request.is_disconnected():
        return

    # Emit images event
    if image_objects:
        yield _sse("images", image_objects)

    # Emit sources event
    if sources:
        yield _sse("sources", sources)

    if await request.is_disconnected():
        return

    # Step 2: Inject conversation history into Ollama messages
    # n8n returns only [system, user_with_context]. We rebuild:
    # [system, ...prior_conversation_turns..., user_with_context]
    chat_messages = chat_body.get("messages", [])
    if len(chat_messages) >= 2 and len(query.messages) > 1:
        system_msg = chat_messages[0]
        rag_user_msg = chat_messages[-1]
        # Insert prior turns between system and current user message
        rebuilt = [system_msg]
        for msg in query.messages[:-1]:
            rebuilt.append({"role": msg.role, "content": msg.content})
        rebuilt.append(rag_user_msg)
        chat_body["messages"] = rebuilt

    # Stream tokens from Ollama
    ollama_body = {**chat_body, "stream": True}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{config.OLLAMA_BASE_URL}/api/chat",
                json=ollama_body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if await request.is_disconnected():
                        logger.info("Client disconnected, stopping Ollama stream")
                        break
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("done"):
                        break
                    content = data.get("message", {}).get("content", "")
                    if content:
                        total_tokens += 1
                        yield _sse("token", {"content": content})
    except httpx.TimeoutException:
        logger.warning("Ollama stream timeout")
        yield _sse("error", {"message": "Ollama response timeout"})
    except Exception as e:
        logger.error("Ollama stream error: %s", e)
        yield _sse("error", {"message": f"Ollama stream error: {e}"})

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    yield _sse("done", {"total_tokens": total_tokens, "elapsed_ms": elapsed_ms})
