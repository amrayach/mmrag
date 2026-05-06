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
from app import trace as _trace

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
FIRST_TOKEN_TIMEOUT = 90
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5:7b-instruct")
N8N_HEALTH_URL = N8N_WEBHOOK.rsplit("/webhook/", 1)[0] + "/healthz"
CONTEXT_MODE = os.getenv("CONTEXT_MODE", "direct")  # "direct" or "n8n"

_VALID_THINK_LEVELS = {"low", "medium", "high"}


def _parse_think_env() -> bool | str:
    """Parse OLLAMA_THINK into the value Ollama's /api/chat `think` field expects.

    - "false" / "0" / "no" / "" / unset → False (default; reasoning suppressed)
    - "true" / "1" / "yes"              → True (allow reasoning before content)
    - "low" / "medium" / "high"         → passed through (gpt-oss-style levels)

    Anything else logs a warning and falls back to False so a typo cannot
    poison every /api/chat request.
    """
    raw = os.getenv("OLLAMA_THINK", "false").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no", ""):
        return False
    if raw in _VALID_THINK_LEVELS:
        return raw
    logger.warning("Invalid OLLAMA_THINK=%r; falling back to False", raw)
    return False


OLLAMA_THINK_VALUE = _parse_think_env()


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


app = FastAPI(title="rag-gateway", version="0.7.0", lifespan=lifespan)


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
    chat_body = {**chat_body, "stream": True, "think": OLLAMA_THINK_VALUE}

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
    chat_body = {**chat_body, "stream": False, "think": OLLAMA_THINK_VALUE}
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


async def _get_context(
    req: ChatRequest,
    req_id: str,
    stream: bool = False,
    trace: _trace.RetrievalTrace | None = None,
) -> dict:
    """Dispatch context retrieval based on CONTEXT_MODE."""
    if CONTEXT_MODE == "direct":
        try:
            extract_t0 = time.perf_counter()
            query = last_user_text(req.messages)
            if trace is not None:
                trace.add_timing(
                    "last_user_message_extraction_ms",
                    (time.perf_counter() - extract_t0) * 1000.0,
                )
            result = await context.get_context_direct(
                query=query,
                messages=[m.model_dump() for m in req.messages],
                model=req.model or DEFAULT_MODEL,
                temperature=req.temperature if req.temperature is not None else 0.2,
                max_tokens=req.max_tokens if req.max_tokens is not None else 800,
                trace=trace,
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


# ---------------------------------------------------------------------------
# Internal-only diagnostic endpoint: production retrieval, no LLM generation
# ---------------------------------------------------------------------------
# Same interface as /v1/chat/completions but returns the retrieval trace
# record (candidates, final context, sources/images, timings) instead of
# generating an answer. Used by scripts/diagnose_bmw_p04.py and other
# diagnostic tooling so they share the production retrieval path. Reachable
# only via the gateway's existing 127.0.0.1:56155 host port; no new ports
# or 0.0.0.0 exposure.


if _trace.RAG_TRACE_ENABLED:

    @app.post("/v1/diagnostic/retrieval")
    async def diagnostic_retrieval(req: ChatRequest):
        if CONTEXT_MODE != "direct":
            raise HTTPException(
                status_code=400,
                detail="diagnostic/retrieval requires CONTEXT_MODE=direct",
            )
        req_id = "diag-" + uuid.uuid4().hex[:8]
        model = req.model or DEFAULT_MODEL
        raw_user_query = last_user_text(req.messages)
        trace = _trace.RetrievalTrace(
            req_id=req_id,
            model_requested=model,
            raw_user_query=raw_user_query,
            force_populate=True,
        )
        trace.persist = False
        total_retrieval_t0 = time.perf_counter()
        try:
            ctx = await _get_context(req, req_id, stream=False, trace=trace)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"retrieval error: {exc}") from exc
        trace.add_timing(
            "total_retrieval_before_llm_ms",
            (time.perf_counter() - total_retrieval_t0) * 1000.0,
        )
        trace.finalize_timings()
        if trace.persist:
            trace.write()
        return {
            "req_id": req_id,
            "model_requested": model,
            "trace": trace.record,
            "image_objects": ctx["image_objects"],
            "sources": ctx["sources"],
            "context_chars": len(ctx["chat_body"].get("messages", [{}, {}])[1].get("content", "")),
        }


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    req_id = uuid.uuid4().hex[:12]
    now = int(time.time())
    resp_id = f"chatcmpl-{uuid.uuid4().hex}"
    model = req.model or DEFAULT_MODEL

    logger.info("[%s] Chat request: model=%s, messages=%d, stream=%s, context_mode=%s",
                req_id, model, len(req.messages), req.stream, CONTEXT_MODE)

    # Build the per-request retrieval trace. Defaults to no-op (RAG_TRACE=false);
    # when enabled, the JSONL record is appended after context is assembled.
    raw_user_query = last_user_text(req.messages)
    trace = _trace.RetrievalTrace(
        req_id=req_id, model_requested=model, raw_user_query=raw_user_query,
    )

    # Step 1: Get context
    total_retrieval_t0 = time.perf_counter()
    try:
        ctx = await _get_context(req, req_id, stream=bool(req.stream), trace=trace)
    except ContextUnavailableError:
        trace.set("error", "context_unavailable")
        trace.add_timing(
            "total_retrieval_before_llm_ms",
            (time.perf_counter() - total_retrieval_t0) * 1000.0,
        )
        if trace.persist:
            trace.write()
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
    except HTTPException as exc:
        trace.set("error", f"http_exception:{exc.status_code}")
        trace.add_timing(
            "total_retrieval_before_llm_ms",
            (time.perf_counter() - total_retrieval_t0) * 1000.0,
        )
        if trace.persist:
            trace.write()
        raise

    chat_body = ctx["chat_body"]
    suffix = _build_suffix(ctx["image_objects"], ctx["sources"])

    # Finalize total retrieval timing and emit the compact one-liner.
    trace.add_timing(
        "total_retrieval_before_llm_ms",
        (time.perf_counter() - total_retrieval_t0) * 1000.0,
    )
    timings_summary = trace.timings_one_liner()
    if _trace.RAG_TRACE_ENABLED and timings_summary:
        logger.info("[%s] retrieval timings %s", req_id, timings_summary)
    if trace.persist:
        trace.write()

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
