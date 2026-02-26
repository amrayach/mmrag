import json
import logging
import os
import time
import uuid
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging (structured JSON)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("rag-gateway")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
N8N_WEBHOOK = os.getenv("N8N_CHAT_WEBHOOK_URL", "http://n8n:5678/webhook/rag-chat")
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECS", "120"))
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5:7b-instruct")

app = FastAPI(title="rag-gateway", version="0.3.0")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.2
    max_tokens: Optional[int] = 800


def last_user_text(messages: List[ChatMessage]) -> str:
    for m in reversed(messages):
        if m.role == "user":
            return m.content
    return messages[-1].content if messages else ""


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/health/ready")
def health_ready():
    checks = {}
    try:
        r = requests.get(N8N_WEBHOOK.rsplit("/webhook/", 1)[0] + "/healthz", timeout=5)
        checks["n8n"] = "ok" if r.ok else f"status {r.status_code}"
    except Exception as e:
        checks["n8n"] = str(e)
    ok = all(v == "ok" for v in checks.values())
    return {"ok": ok, "checks": checks}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": DEFAULT_MODEL,
                "object": "model",
                "created": 0,
                "owned_by": "mmrag-demo",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _call_n8n(req: ChatRequest):
    req_id = uuid.uuid4().hex[:12]
    query = last_user_text(req.messages)
    payload = {
        "query": query,
        "messages": [m.model_dump() for m in req.messages],
        "model": req.model or DEFAULT_MODEL,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
    }

    logger.info("[%s] Chat request: model=%s, messages=%d, stream=%s",
                req_id, req.model or DEFAULT_MODEL, len(req.messages), req.stream)

    try:
        r = requests.post(N8N_WEBHOOK, json=payload,
                          headers={"X-Request-ID": req_id}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except requests.Timeout:
        logger.warning("[%s] n8n timeout after %ds", req_id, TIMEOUT)
        raise HTTPException(status_code=504, detail="The AI model is busy. Please try again in a moment.")
    except requests.ConnectionError:
        logger.error("[%s] n8n unreachable", req_id)
        raise HTTPException(status_code=503, detail="RAG service temporarily unavailable.")
    except Exception as e:
        logger.error("[%s] n8n error: %s", req_id, e)
        raise HTTPException(status_code=502, detail="An error occurred processing your request.")

    answer = (data.get("answer") or "").strip()
    images = data.get("images") or []
    sources = data.get("sources") or []

    logger.info("[%s] n8n response: %d chars, %d images, %d sources",
                req_id, len(answer), len(images), len(sources))

    if images:
        answer += "\n\n" + "\n".join([f"![image]({u})" for u in images])

    if sources:
        answer += "\n\nQuellen:\n" + "\n".join([f"- {s}" for s in sources])

    return answer


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    answer = _call_n8n(req)
    now = int(time.time())
    resp_id = f"chatcmpl-{uuid.uuid4().hex}"
    model = req.model or DEFAULT_MODEL

    if req.stream:
        def sse_generator():
            chunk = {
                "id": resp_id,
                "object": "chat.completion.chunk",
                "created": now,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": answer}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            done_chunk = {
                "id": resp_id,
                "object": "chat.completion.chunk",
                "created": now,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(done_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    return {
        "id": resp_id,
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
    }
