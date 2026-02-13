import json
import os
import time
import uuid
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

N8N_WEBHOOK = os.getenv("N8N_CHAT_WEBHOOK_URL", "http://n8n:5678/webhook/rag-chat")
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECS", "120"))
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5:7b-instruct")

app = FastAPI(title="rag-gateway", version="0.2.0")


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


@app.get("/health")
def health():
    return {"ok": True}


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


def _call_n8n(req: ChatRequest):
    query = last_user_text(req.messages)
    payload = {
        "query": query,
        "messages": [m.model_dump() for m in req.messages],
        "model": req.model or DEFAULT_MODEL,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
    }

    try:
        r = requests.post(N8N_WEBHOOK, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"n8n webhook failed: {e}")

    answer = (data.get("answer") or "").strip()
    images = data.get("images") or []
    sources = data.get("sources") or []

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
