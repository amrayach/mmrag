"""Direct context retrieval — bypasses n8n for embedding + vector search + context build."""

import logging
import os
import re
from typing import Any

import httpx
import numpy as np
from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger("rag-gateway")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATABASE_HOST = os.getenv("DATABASE_HOST", "postgres")
DATABASE_PORT = os.getenv("DATABASE_PORT", "5432")
DATABASE_NAME = os.getenv("DATABASE_NAME", "rag")
DATABASE_USER = os.getenv("DATABASE_USER", "rag_user")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
PUBLIC_ASSETS_BASE_URL = os.getenv("PUBLIC_ASSETS_BASE_URL", "").rstrip("/")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5:7b-instruct")
VECTOR_DISTANCE_THRESHOLD = float(os.getenv("VECTOR_DISTANCE_THRESHOLD", "0.5"))

SYSTEM_PROMPT = (
    "Du bist ein intelligenter Multimodal-Assistent. "
    "Antworte auf Deutsch und beziehe dich auf den bereitgestellten Kontext. "
    "Wenn der Kontext Bildbeschreibungen (Captions) enthält, weise den Nutzer aktiv darauf hin, "
    "was auf den Bildern zu sehen ist. Zitiere immer deine Quellen "
    "(z.B. 'Laut Seite 4...' oder 'Wie im Bild auf Seite 2 zu sehen ist...')."
)

_PREAMBLE_RE = re.compile(
    r"^(Basierend auf|Laut den Dokumenten|Gemäß|Auf Grundlage|Den Dokumenten zufolge)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Module-level resources (initialized/closed via init_pool / close_pool)
# ---------------------------------------------------------------------------
_pool: AsyncConnectionPool | None = None
_http: httpx.AsyncClient | None = None


async def init_pool() -> None:
    global _pool, _http
    conninfo = (
        f"host={DATABASE_HOST} port={DATABASE_PORT} dbname={DATABASE_NAME} "
        f"user={DATABASE_USER} password={DATABASE_PASSWORD}"
    )

    async def _configure(conn):
        await register_vector_async(conn)

    _pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=3,
        configure=_configure,
        open=False,
    )
    await _pool.open()
    _http = httpx.AsyncClient(timeout=15.0)
    logger.info(
        "Direct context pool opened (postgres=%s:%s/%s)",
        DATABASE_HOST, DATABASE_PORT, DATABASE_NAME,
    )


async def close_pool() -> None:
    global _pool, _http
    if _pool:
        await _pool.close()
        _pool = None
    if _http:
        await _http.aclose()
        _http = None
    logger.info("Direct context pool closed")


# ---------------------------------------------------------------------------
# Step 1: Query preprocessing (follow-up rewriting + @doc filter)
# ---------------------------------------------------------------------------


def _preprocess_query(query: str, messages: list[dict]) -> tuple[str, str | None]:
    """Return (processed_query, doc_filter_or_None)."""
    # Follow-up rewriting: append hint from last assistant message
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    if assistant_msgs and len(query) < 100:
        hint = assistant_msgs[-1].get("content", "")
        if _PREAMBLE_RE.match(hint):
            end = re.search(r"[.!?:]\s", hint)
            if end and end.start() < 150:
                hint = hint[end.end():]
        hint = hint[:150].strip()
        query = f"{query} {hint}"

    # @filename document filter
    doc_filter = None
    if query.startswith("@"):
        space_idx = query.find(" ")
        if space_idx > 0:
            doc_filter = re.sub(r"[^\w.\-]", "_", query[1:space_idx])
            query = query[space_idx + 1:].strip()

    return query, doc_filter


# ---------------------------------------------------------------------------
# Step 2: Embed query via Ollama
# ---------------------------------------------------------------------------


async def _embed_query(query: str) -> list[float]:
    resp = await _http.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json={"model": OLLAMA_EMBED_MODEL, "prompt": query},
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


# ---------------------------------------------------------------------------
# Step 3: Vector search in pgvector
# ---------------------------------------------------------------------------

_SEARCH_SQL_BASE = """\
SELECT doc_id, chunk_type, page, content_text, caption, asset_path, meta,
       1 - (embedding <=> %(emb)s) AS score
FROM rag_chunks
WHERE embedding IS NOT NULL
  AND embedding <=> %(emb)s < %(threshold)s"""

_SEARCH_SQL_DOC_FILTER = """
  AND doc_id IN (
    SELECT doc_id FROM rag_docs
    WHERE filename ILIKE '%%' || %(doc_filter)s || '%%'
  )"""

_SEARCH_SQL_ORDER = """
ORDER BY embedding <=> %(emb)s
LIMIT 8"""


async def _vector_search(
    embedding: list[float], doc_filter: str | None,
) -> list[dict]:
    emb = np.array(embedding, dtype=np.float32)
    sql = _SEARCH_SQL_BASE
    params: dict[str, Any] = {
        "emb": emb,
        "threshold": VECTOR_DISTANCE_THRESHOLD,
    }
    if doc_filter:
        sql += _SEARCH_SQL_DOC_FILTER
        params["doc_filter"] = doc_filter
    sql += _SEARCH_SQL_ORDER

    async with _pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


# ---------------------------------------------------------------------------
# Step 4: Build context (ported from n8n Build Context node)
# ---------------------------------------------------------------------------


def _build_context(
    hits: list[dict], query: str, model: str,
    temperature: float, max_tokens: int,
) -> dict:
    base = PUBLIC_ASSETS_BASE_URL

    text_hits = [h for h in hits if h["chunk_type"] == "text"]
    image_hits = [h for h in hits if h["chunk_type"] == "image"]
    image_dominant = len(image_hits) > len(text_hits)
    text_doc_ids = {h["doc_id"] for h in text_hits}

    best_text_score = max((h["score"] for h in text_hits), default=0)
    image_score_threshold = best_text_score * 0.6

    def show_image(h: dict) -> bool:
        if h["chunk_type"] != "image" or not h.get("asset_path"):
            return False
        if h["score"] < image_score_threshold:
            return False
        return image_dominant or h["doc_id"] in text_doc_ids

    # Image objects for suffix
    image_objects = [
        {"url": f"{base}/{h['asset_path']}", "caption": h.get("caption") or "Bild"}
        for h in hits
        if h["chunk_type"] == "image" and show_image(h) and h.get("asset_path")
    ]

    # Context lines
    ctx_lines: list[str] = []
    for h in hits:
        meta = h.get("meta") or {}
        is_rss = meta.get("content_type") == "rss_article"
        if h["chunk_type"] == "image":
            if not show_image(h):
                continue
            url = f"{base}/{h['asset_path']}" if h.get("asset_path") else ""
            src = (
                f"Bild ({meta.get('feed_name') or 'RSS'})"
                if is_rss
                else f"Bild (Seite {h['page']})"
            )
            ctx_lines.append(f"{src}: {h.get('caption') or ''} {url}".strip())
        elif is_rss:
            ctx_lines.append(
                f"Quelle {meta.get('feed_name') or 'RSS'} "
                f"- \"{meta.get('title') or ''}\": {h.get('content_text') or ''}"
            )
        else:
            ctx_lines.append(f"Text (Seite {h['page']}): {h.get('content_text') or ''}")

    # Sources (max 8, markdown links for RSS)
    sources: list[str] = []
    for h in hits:
        if h["chunk_type"] == "image" and not show_image(h):
            continue
        meta = h.get("meta") or {}
        if meta.get("content_type") == "rss_article":
            title = (meta.get("title") or "")[:60]
            if meta.get("url"):
                sources.append(
                    f"[{meta.get('feed_name') or 'RSS'}: {title}]({meta['url']})"
                )
            else:
                sources.append(f"{meta.get('feed_name') or 'RSS'}: {title}")
        else:
            sources.append(f"Seite {h['page']} ({h['chunk_type']})")
    sources = sources[:8]

    context_text = "\n\n".join(ctx_lines)
    chat_request_body = {
        "model": model,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Frage: {query}\n\n"
                    f"Kontext aus Dokumenten und Nachrichten:\n{context_text}\n\n"
                    "Antworte kurz, korrekt und mit Quellenhinweisen."
                ),
            },
        ],
    }

    return {
        "chatRequestBody": chat_request_body,
        "imageObjects": image_objects,
        "sources": sources,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_context_direct(
    query: str,
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict:
    """Full direct context pipeline: preprocess -> embed -> search -> build."""
    processed_query, doc_filter = _preprocess_query(query, messages)
    embedding = await _embed_query(processed_query)
    hits = await _vector_search(embedding, doc_filter)
    logger.info(
        "Direct context: %d hits (query=%r, doc_filter=%s)",
        len(hits), query[:80], doc_filter,
    )
    return _build_context(hits, processed_query, model, temperature, max_tokens)
