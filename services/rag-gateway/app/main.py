import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import context

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
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECS", "120"))
OLLAMA_TIMEOUT = 300
FIRST_TOKEN_TIMEOUT = 45
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5:7b-instruct")
N8N_HEALTH_URL = N8N_WEBHOOK.rsplit("/webhook/", 1)[0] + "/healthz"
CONTEXT_MODE = os.getenv("CONTEXT_MODE", "direct")  # "direct" or "n8n"


class ContextUnavailableError(Exception):
    """Raised when context retrieval fails during streaming."""
    pass


# ---------------------------------------------------------------------------
# Lifespan: init/close direct-context pool
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    if CONTEXT_MODE == "direct":
        await context.init_pool()
    logger.info("rag-gateway started (context_mode=%s)", CONTEXT_MODE)
    yield
    if CONTEXT_MODE == "direct":
        await context.close_pool()


app = FastAPI(title="rag-gateway", version="0.6.0", lifespan=lifespan)


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
    if CONTEXT_MODE == "n8n":
        try:
            r = requests.get(N8N_HEALTH_URL, timeout=5)
            checks["n8n"] = "ok" if r.ok else f"status {r.status_code}"
        except Exception as e:
            checks["n8n"] = str(e)
    else:
        try:
            import psycopg
            conninfo = (
                f"host={context.DATABASE_HOST} port={context.DATABASE_PORT} "
                f"dbname={context.DATABASE_NAME} user={context.DATABASE_USER} "
                f"password={context.DATABASE_PASSWORD}"
            )
            with psycopg.connect(conninfo, connect_timeout=5) as conn:
                conn.execute("SELECT 1")
            checks["postgres"] = "ok"
        except Exception as e:
            checks["postgres"] = str(e)
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/version", timeout=5)
        checks["ollama"] = "ok" if r.ok else f"status {r.status_code}"
    except Exception as e:
        checks["ollama"] = str(e)
    checks["context_mode"] = CONTEXT_MODE
    ok = all(v == "ok" for k, v in checks.items() if k != "context_mode")
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
# Step 1: Get context from n8n (embedding + vector search + context build)
# ---------------------------------------------------------------------------


def _get_context_from_n8n(req: ChatRequest, req_id: str, stream: bool = False) -> dict:
    # Pre-check: fast-fail if n8n is not ready (3s timeout)
    try:
        h = requests.get(N8N_HEALTH_URL, timeout=3)
        if h.status_code != 200:
            raise requests.ConnectionError(f"n8n health returned {h.status_code}")
    except requests.RequestException:
        logger.warning("[%s] n8n health pre-check failed — fast-failing", req_id)
        if stream:
            raise ContextUnavailableError()
        raise HTTPException(
            status_code=503,
            detail="Das KI-System wird gerade initialisiert. Bitte in 30 Sekunden erneut versuchen.",
        )

    query = last_user_text(req.messages)
    payload = {
        "query": query,
        "messages": [m.model_dump() for m in req.messages],
        "model": req.model or DEFAULT_MODEL,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
    }

    logger.info("[%s] Context request to n8n: model=%s, messages=%d",
                req_id, req.model or DEFAULT_MODEL, len(req.messages))

    try:
        r = requests.post(N8N_WEBHOOK, json=payload,
                          headers={"X-Request-ID": req_id}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except requests.Timeout:
        logger.warning("[%s] n8n context timeout after %ds", req_id, TIMEOUT)
        raise HTTPException(status_code=504, detail="Das Sprachmodell ist ausgelastet. Bitte in einem Moment erneut versuchen.")
    except requests.ConnectionError:
        logger.error("[%s] n8n unreachable", req_id)
        raise HTTPException(status_code=503, detail="Der RAG-Dienst ist vorübergehend nicht verfügbar.")
    except Exception as e:
        logger.error("[%s] n8n error: %s", req_id, e)
        raise HTTPException(status_code=502, detail="Bei der Verarbeitung ist ein Fehler aufgetreten.")

    image_objects = data.get("imageObjects") or []
    sources = data.get("sources") or []
    chat_body = data.get("chatRequestBody") or {}

    logger.info("[%s] n8n context: %d imageObjects, %d sources, model=%s",
                req_id, len(image_objects), len(sources), chat_body.get("model", "?"))

    return {
        "chat_body": chat_body,
        "image_objects": image_objects,
        "sources": sources,
    }


# ---------------------------------------------------------------------------
# Helper: build the suffix (images + sources) appended after LLM answer
# ---------------------------------------------------------------------------


def _build_suffix(image_objects: list, sources: list) -> str:
    parts = []
    if image_objects:
        parts.append("")
        for img in image_objects:
            caption = img.get("caption", "Bild")
            url = img.get("url", "")
            parts.append(f"![{caption}]({url})")
    if sources:
        parts.append("")
        parts.append("Quellen:")
        for s in sources:
            parts.append(f"- {s}")
    return "\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Step 2+3: Stream from Ollama, translate NDJSON → OpenAI SSE
# ---------------------------------------------------------------------------


def _stream_from_ollama(chat_body: dict, suffix: str,
                        resp_id: str, model: str, now: int, req_id: str):
    chat_body = {**chat_body, "stream": True}

    first_chunk = True
    got_first_content = False

    def make_chunk(delta, finish_reason=None):
        return {
            "id": resp_id,
            "object": "chat.completion.chunk",
            "created": now,
            "model": model,
            "choices": [{"index": 0, "delta": delta,
                         "finish_reason": finish_reason}],
        }

    try:
        with requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=chat_body, stream=True, timeout=(10, FIRST_TOKEN_TIMEOUT)
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("done"):
                    break
                content = data.get("message", {}).get("content", "")
                if not content:
                    continue
                got_first_content = True
                delta = {"content": content}
                if first_chunk:
                    delta["role"] = "assistant"
                    first_chunk = False
                yield f"data: {json.dumps(make_chunk(delta))}\n\n"

    except requests.Timeout:
        if not got_first_content:
            logger.warning("[%s] Ollama first-token timeout after %ds", req_id, FIRST_TOKEN_TIMEOUT)
            err = make_chunk({"content": "\n\n[Das Sprachmodell ist gerade beschäftigt. Bitte kurz warten und erneut versuchen.]"})
        else:
            logger.warning("[%s] Ollama stream timeout", req_id)
            err = make_chunk({"content": "\n\n[Das Sprachmodell antwortet nicht — bitte erneut versuchen.]"})
        yield f"data: {json.dumps(err)}\n\n"
    except requests.ConnectionError:
        logger.error("[%s] Ollama unreachable during streaming", req_id)
        err = make_chunk({"content": "\n\n[Fehler: KI-Modell nicht erreichbar]"})
        yield f"data: {json.dumps(err)}\n\n"
    except Exception as e:
        logger.error("[%s] Ollama stream error: %s", req_id, e)
        err = make_chunk({"content": f"\n\n[Fehler bei der Antwortgenerierung: {e}]"})
        yield f"data: {json.dumps(err)}\n\n"

    # Step 4: Yield suffix chunk with images and sources
    if suffix:
        suffix_delta = {"content": suffix}
        if first_chunk:
            suffix_delta["role"] = "assistant"
            first_chunk = False
        yield f"data: {json.dumps(make_chunk(suffix_delta))}\n\n"

    # Final stop chunk
    yield f"data: {json.dumps(make_chunk({}, finish_reason='stop'))}\n\n"
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Non-streaming fallback: call Ollama synchronously
# ---------------------------------------------------------------------------


def _call_ollama_sync(chat_body: dict, req_id: str) -> str:
    chat_body = {**chat_body, "stream": False}
    try:
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=chat_body, timeout=OLLAMA_TIMEOUT
        )
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")
    except requests.Timeout:
        logger.warning("[%s] Ollama timeout after %ds", req_id, OLLAMA_TIMEOUT)
        raise HTTPException(status_code=504, detail="The AI model is busy. Please try again in a moment.")
    except requests.ConnectionError:
        logger.error("[%s] Ollama unreachable", req_id)
        raise HTTPException(status_code=503, detail="AI model service temporarily unavailable.")
    except Exception as e:
        logger.error("[%s] Ollama error: %s", req_id, e)
        raise HTTPException(status_code=502, detail="An error occurred generating the response.")


# ---------------------------------------------------------------------------
# Step 1 (dispatch): Get context via direct path or n8n
# ---------------------------------------------------------------------------


async def _get_context(req: ChatRequest, req_id: str, stream: bool = False) -> dict:
    """Dispatch context retrieval based on CONTEXT_MODE."""
    if CONTEXT_MODE == "direct":
        try:
            query = last_user_text(req.messages)
            result = await context.get_context_direct(
                query=query,
                messages=[m.model_dump() for m in req.messages],
                model=req.model or DEFAULT_MODEL,
                temperature=req.temperature if req.temperature is not None else 0.2,
                max_tokens=req.max_tokens if req.max_tokens is not None else 800,
            )
            return {
                "chat_body": result["chatRequestBody"],
                "image_objects": result["imageObjects"],
                "sources": result["sources"],
            }
        except Exception as e:
            logger.error("[%s] Direct context error: %s", req_id, e)
            if stream:
                raise ContextUnavailableError()
            raise HTTPException(
                status_code=502,
                detail="Fehler bei der Kontextabfrage. Bitte erneut versuchen.",
            )
    else:
        # n8n mode — sync code, safe in FastAPI sync-compatible call
        return _get_context_from_n8n(req, req_id, stream)


# ---------------------------------------------------------------------------
# OpenAI-compatible chat completions endpoint
# ---------------------------------------------------------------------------


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    req_id = uuid.uuid4().hex[:12]
    now = int(time.time())
    resp_id = f"chatcmpl-{uuid.uuid4().hex}"
    model = req.model or DEFAULT_MODEL

    logger.info("[%s] Chat request: model=%s, messages=%d, stream=%s, context_mode=%s",
                req_id, model, len(req.messages), req.stream, CONTEXT_MODE)

    # Step 1: Get context
    try:
        ctx = await _get_context(req, req_id, stream=bool(req.stream))
    except ContextUnavailableError:
        msg = "Das KI-System ist vorübergehend nicht erreichbar. Bitte in 30 Sekunden erneut versuchen."
        logger.warning("[%s] Returning SSE context-unavailable error to streaming client", req_id)

        def _ctx_error():
            chunk = {
                "id": resp_id, "object": "chat.completion.chunk",
                "created": now, "model": model,
                "choices": [{"index": 0,
                             "delta": {"role": "assistant", "content": f"\n\n[{msg}]"},
                             "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            stop = {
                "id": resp_id, "object": "chat.completion.chunk",
                "created": now, "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(stop)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_ctx_error(), media_type="text/event-stream")

    chat_body = ctx["chat_body"]
    suffix = _build_suffix(ctx["image_objects"], ctx["sources"])

    if req.stream:
        # Steps 2-4: Stream from Ollama with SSE translation
        return StreamingResponse(
            _stream_from_ollama(chat_body, suffix, resp_id, model, now, req_id),
            media_type="text/event-stream",
        )

    # Non-streaming fallback
    answer = _call_ollama_sync(chat_body, req_id)
    if suffix:
        answer += suffix

    logger.info("[%s] Non-streaming response: %d chars", req_id, len(answer))

    return {
        "id": resp_id,
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
    }
