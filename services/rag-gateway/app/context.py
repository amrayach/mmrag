"""Direct context retrieval — bypasses n8n for embedding + vector search + context build."""

import logging
import os
import re
import time
from typing import Any

import httpx
import numpy as np
from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app import trace as _trace

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
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
PUBLIC_ASSETS_BASE_URL = os.getenv("PUBLIC_ASSETS_BASE_URL", "").rstrip("/")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5:7b-instruct")
VECTOR_DISTANCE_THRESHOLD = float(os.getenv("VECTOR_DISTANCE_THRESHOLD", "0.6"))

SYSTEM_PROMPT = (
    "Du bist ein intelligenter Multimodal-Assistent. "
    "Antworte auf Deutsch und beziehe dich auf den bereitgestellten Kontext. "
    "Wenn der Kontext Bildbeschreibungen (Captions) enthält, weise den Nutzer aktiv darauf hin, "
    "was auf den Bildern zu sehen ist. Zitiere immer deine Quellen "
    "(z.B. 'Laut Seite 4...' oder 'Wie im Bild auf Seite 2 zu sehen ist...'). "
    "Zeige Bilder nur, wenn sie direkt zur Frage des Nutzers passen. "
    "Zeige keine generischen oder thematisch unpassenden Bilder."
)

_IMAGE_QUERY_RE = re.compile(
    r"\b(bild|bilder|zeige|foto|abbildung|grafik|diagramm|image|show)\b",
    re.IGNORECASE,
)

# Deictic/anaphoric words that signal a follow-up referencing prior context
_DEICTIC_RE = re.compile(
    r"\b(dabei|dazu|davon|hierzu|hierbei|hierauf|hierin|"
    r"darüber|darin|darunter|daneben|"
    r"deren|dessen|diesem|diesen|dieser)\b",
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


def _preprocess_query(
    query: str, messages: list[dict],
) -> tuple[str, str | None, str | None, dict]:
    """Return (processed_query, doc_filter_or_None, source_type_or_None, meta).

    ``meta`` carries rewrite/filter provenance for tracing without changing
    behavior: ``followup_rewrite_triggered``, ``deictic_match``,
    ``deictic_token``, and the unmodified ``raw_query``. Behavior is
    bit-identical to the previous 3-tuple version.
    """
    raw_query = query
    deictic_m = _DEICTIC_RE.search(query)
    deictic_token = deictic_m.group(0) if deictic_m else None
    followup_rewrite_triggered = False

    # Follow-up rewriting: prepend prior user query for context continuity.
    # Triggers on short queries OR queries with deictic/anaphoric references
    # (dabei, dazu, davon, hierzu, diesem, etc.) that reference prior context.
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if len(user_msgs) >= 2:
        needs_rewrite = len(query) < 50 or bool(deictic_m)
        if needs_rewrite:
            prev = user_msgs[-2].get("content", "")[:120].strip()
            if prev:
                query = f"Bezugnehmend auf: {prev} — {query}"
                followup_rewrite_triggered = True

    # @rss / @pdf → source_type filter; other @tokens → doc_filter
    doc_filter = None
    source_type = None
    if query.startswith("@"):
        space_idx = query.find(" ")
        if space_idx > 0:
            token = query[1:space_idx].lower()
            if token == "rss":
                source_type = "rss"
            elif token == "pdf":
                source_type = "pdf"
            else:
                doc_filter = re.sub(r"[^\w.\-]", "_", query[1:space_idx])
            query = query[space_idx + 1:].strip()

    meta = {
        "raw_query": raw_query,
        "followup_rewrite_triggered": followup_rewrite_triggered,
        "deictic_match": bool(deictic_m),
        "deictic_token": deictic_token,
    }
    return query, doc_filter, source_type, meta


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
SELECT c.id, c.doc_id, c.chunk_type, c.page, c.content_text, c.caption,
       c.asset_path, c.meta, d.filename AS doc_filename,
       d.pages AS doc_pages, d.lang AS doc_lang,
       1 - (c.embedding <=> %(emb)s) AS score
FROM rag_chunks c
JOIN rag_docs d ON c.doc_id = d.doc_id
WHERE c.embedding IS NOT NULL
  AND c.embedding <=> %(emb)s < %(threshold)s"""

_SEARCH_SQL_DOC_FILTER = """
  AND d.filename ILIKE '%%' || %(doc_filter)s || '%%'"""

_SEARCH_SQL_CHUNK_TYPE = """
  AND c.chunk_type = %(chunk_type)s"""

_SEARCH_SQL_ORDER = """
ORDER BY c.embedding <=> %(emb)s
LIMIT %(limit)s"""

_SEARCH_SQL_SOURCE_RSS = """
  AND d.filename LIKE 'http%%'"""

_SEARCH_SQL_SOURCE_PDF = """
  AND d.filename NOT LIKE 'http%%'"""


async def _vector_search(
    embedding: list[float],
    doc_filter: str | None,
    source_type: str | None = None,
    chunk_type: str | None = None,
    limit: int = 8,
) -> list[dict]:
    emb = np.array(embedding, dtype=np.float32)
    sql = _SEARCH_SQL_BASE
    params: dict[str, Any] = {
        "emb": emb,
        "threshold": VECTOR_DISTANCE_THRESHOLD,
        "limit": limit,
    }
    if doc_filter:
        sql += _SEARCH_SQL_DOC_FILTER
        params["doc_filter"] = doc_filter
    if source_type == "rss":
        sql += _SEARCH_SQL_SOURCE_RSS
    elif source_type == "pdf":
        sql += _SEARCH_SQL_SOURCE_PDF
    if chunk_type:
        sql += _SEARCH_SQL_CHUNK_TYPE
        params["chunk_type"] = chunk_type
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
    trace: _trace.RetrievalTrace | None = None,
) -> dict:
    base = PUBLIC_ASSETS_BASE_URL

    # Image relevance thresholds must stay above the SQL score floor:
    # score > 1 - VECTOR_DISTANCE_THRESHOLD (0.4 when threshold is 0.6).
    query_wants_images = bool(_IMAGE_QUERY_RE.search(query))
    image_score_min = 0.45 if query_wants_images else 0.55
    max_images = 3 if query_wants_images else 2

    # Cross-doc-id guard: non-image queries only show images from docs with text hits
    text_doc_ids = {h["doc_id"] for h in hits if h["chunk_type"] == "text"}

    # Pre-select approved images (hits ordered by score desc).
    # When tracing, also remember which guard dropped each image so the
    # candidates_image_before_selection record can be annotated.
    _filter_t0 = time.perf_counter()
    _approved_images: set[int] = set()
    _img_count = 0
    _drop_reason: dict[int, str] = {}
    for h in hits:
        if h["chunk_type"] != "image" or not h.get("asset_path"):
            continue
        if h["score"] < image_score_min:
            _drop_reason.setdefault(id(h), "image_score_min")
            continue
        if not query_wants_images and h["doc_id"] not in text_doc_ids:
            _drop_reason.setdefault(id(h), "cross_doc_id_guard")
            continue
        if _img_count >= max_images:
            break
        _approved_images.add(id(h))
        _img_count += 1
    if trace is not None:
        trace.add_timing(
            "image_filter_and_cross_doc_guard_ms",
            (time.perf_counter() - _filter_t0) * 1000.0,
        )

    def show_image(h: dict) -> bool:
        return id(h) in _approved_images

    # Image objects for suffix (deduplicated by asset_path)
    _build_t0 = time.perf_counter()
    _seen_assets: set[str] = set()
    image_objects: list[dict] = []
    for h in hits:
        if h["chunk_type"] != "image" or not show_image(h) or not h.get("asset_path"):
            continue
        if h["asset_path"] in _seen_assets:
            continue
        _seen_assets.add(h["asset_path"])
        image_objects.append(
            {"url": f"{base}/{h['asset_path']}", "caption": h.get("caption") or "Bild"}
        )

    # Context lines
    ctx_lines: list[str] = []
    final_context_chunks: list[dict] = []
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
            if trace is not None and trace.enabled:
                rec = {
                    "chunk_id": h.get("id"),
                    "doc_id": str(h.get("doc_id")) if h.get("doc_id") is not None else None,
                    "filename": h.get("doc_filename"),
                    "source_label": "image",
                    "page": h.get("page"),
                    "score": round(float(h.get("score", 0.0)), 4),
                    "order_in_context": len(ctx_lines) - 1,
                    "chunk_type": "image",
                }
                _trace.enrich_final_context_chunk(rec, h)
                final_context_chunks.append(rec)
        elif is_rss:
            ctx_lines.append(
                f"Quelle {meta.get('feed_name') or 'RSS'} "
                f"- \"{meta.get('title') or ''}\": {h.get('content_text') or ''}"
            )
            if trace is not None and trace.enabled:
                rec = {
                    "chunk_id": h.get("id"),
                    "doc_id": str(h.get("doc_id")) if h.get("doc_id") is not None else None,
                    "filename": h.get("doc_filename"),
                    "source_label": "rss-text",
                    "page": h.get("page"),
                    "score": round(float(h.get("score", 0.0)), 4),
                    "order_in_context": len(ctx_lines) - 1,
                    "chunk_type": "text",
                }
                _trace.enrich_final_context_chunk(rec, h)
                final_context_chunks.append(rec)
        else:
            ctx_lines.append(f"Text (Seite {h['page']}): {h.get('content_text') or ''}")
            if trace is not None and trace.enabled:
                rec = {
                    "chunk_id": h.get("id"),
                    "doc_id": str(h.get("doc_id")) if h.get("doc_id") is not None else None,
                    "filename": h.get("doc_filename"),
                    "source_label": "pdf-text",
                    "page": h.get("page"),
                    "score": round(float(h.get("score", 0.0)), 4),
                    "order_in_context": len(ctx_lines) - 1,
                    "chunk_type": "text",
                }
                _trace.enrich_final_context_chunk(rec, h)
                final_context_chunks.append(rec)

    # Sources (max 8, markdown links for both RSS and PDF)
    sources: list[str] = []
    _seen_urls: set[str] = set()
    _seen_pdf_pages: set[str] = set()  # "filename:page" dedup
    for h in hits:
        if h["chunk_type"] == "image" and not show_image(h):
            continue
        meta = h.get("meta") or {}
        if meta.get("content_type") == "rss_article":
            url = meta.get("url", "")
            if url and url in _seen_urls:
                continue
            if url:
                _seen_urls.add(url)
            title = (meta.get("title") or "")[:60]
            if url:
                sources.append(
                    f"[{meta.get('feed_name') or 'RSS'}: {title}]({url})"
                )
            else:
                sources.append(f"{meta.get('feed_name') or 'RSS'}: {title}")
        else:
            doc_fn = h.get("doc_filename") or ""
            page_key = f"{doc_fn}:{h['page']}"
            if page_key in _seen_pdf_pages:
                continue
            _seen_pdf_pages.add(page_key)
            if doc_fn and PUBLIC_ASSETS_BASE_URL:
                from urllib.parse import quote
                pdf_url = f"{PUBLIC_ASSETS_BASE_URL}/pdf/{quote(doc_fn)}#page={h['page']}"
                label = doc_fn.replace(".pdf", "").replace("_", " ")
                sources.append(f"[{label} — Seite {h['page']}]({pdf_url})")
            else:
                sources.append(f"Seite {h['page']} ({h['chunk_type']})")
    sources = sources[:8]

    context_text = "\n\n".join(ctx_lines)
    chat_request_body = {
        "model": model,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "num_ctx": 4096,
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

    if trace is not None:
        trace.add_timing(
            "context_assembly_ms",
            (time.perf_counter() - _build_t0) * 1000.0,
        )
        if trace.enabled:
            trace.set("final_context_chunks", final_context_chunks)
            trace.set("context_char_count", len(context_text))
            trace.set("context_token_estimate", len(context_text) // 4)
            trace.set("sources_in_final_suffix", list(sources))
            trace.set(
                "images_in_final_suffix",
                [
                    {"url": img["url"], "caption": img.get("caption", "")}
                    for img in image_objects
                ],
            )
            # Backfill dropped_by_* on already-stored image candidates
            cand_imgs = trace.record.get("candidates_image_before_selection") if trace.record else None
            if cand_imgs:
                # Rebuild a lookup from chunk_id → drop_reason via parallel hit list
                # by walking hits the same way.
                reason_by_chunk_id: dict[Any, str] = {}
                for h in hits:
                    if h["chunk_type"] != "image":
                        continue
                    r = _drop_reason.get(id(h))
                    if r is not None:
                        reason_by_chunk_id[h.get("id")] = r
                for cand in cand_imgs:
                    r = reason_by_chunk_id.get(cand.get("chunk_id"))
                    if r == "image_score_min":
                        cand["dropped_by_image_score_min"] = True
                    elif r == "cross_doc_id_guard":
                        cand["dropped_by_cross_doc_id_guard"] = True

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
    trace: _trace.RetrievalTrace | None = None,
) -> dict:
    """Full direct context pipeline: preprocess -> embed -> dual search -> build.

    ``trace`` is optional and additive: when present, retrieval evidence and
    per-stage timings are recorded. Response behavior is identical to the
    pre-trace path when ``trace`` is None or RAG_TRACE is disabled.
    """
    if trace is None:
        trace = _trace.RetrievalTrace(req_id="-", model_requested=model, raw_user_query=query)

    with trace.time("followup_rewrite_and_filter_parsing_ms"):
        processed_query, doc_filter, source_type, pre_meta = _preprocess_query(query, messages)

    if trace.enabled:
        trace.set("rewritten_query", (processed_query or "")[:1000])
        trace.set("followup_rewrite_triggered", bool(pre_meta["followup_rewrite_triggered"]))
        trace.set("deictic_match", bool(pre_meta["deictic_match"]))
        trace.set("deictic_token", pre_meta["deictic_token"])
        trace.set(
            "parsed_filters",
            {"source_type": source_type, "doc_filter": doc_filter},
        )

    with trace.time("query_embedding_ms"):
        embedding = await _embed_query(processed_query)

    # Dual retrieval: reserve slots for both text and images
    query_wants_images = bool(_IMAGE_QUERY_RE.search(processed_query))
    query_wants_cross_source = False
    text_limit = 4 if query_wants_images else 6
    image_limit = 4 if query_wants_images else 2

    if trace.enabled:
        image_score_min_used = 0.45 if query_wants_images else 0.55
        max_images_used = 3 if query_wants_images else 2
        trace.set(
            "routing",
            {
                "image_intent_detected": bool(query_wants_images),
                "cross_source_branch_triggered": bool(query_wants_cross_source),
            },
        )
        trace.set(
            "retrieval_config",
            {
                "query_embedding_model": OLLAMA_EMBED_MODEL,
                "vector_distance_threshold": VECTOR_DISTANCE_THRESHOLD,
                "text_limit": text_limit,
                "image_limit": image_limit,
                "image_score_min_used": image_score_min_used,
                "max_images_used": max_images_used,
                "score_boost_applied": 0.10 if doc_filter else 0.0,
            },
        )

    sql_total_t0 = time.perf_counter()
    with trace.time("vector_sql_text_ms"):
        text_hits = await _vector_search(
            embedding, doc_filter, source_type, chunk_type="text", limit=text_limit,
        )
    with trace.time("vector_sql_image_ms"):
        image_hits = await _vector_search(
            embedding, doc_filter, source_type, chunk_type="image", limit=image_limit,
        )
    trace.add_timing(
        "vector_sql_total_ms",
        (time.perf_counter() - sql_total_t0) * 1000.0,
    )

    # Boost image scores when doc_filter narrows to a specific document —
    # images from that document are topically relevant even if captions
    # don't match the query embedding perfectly.
    if doc_filter:
        for h in image_hits:
            h["score"] = h["score"] + 0.10

    if trace.enabled:
        trace.set(
            "candidates_text_before_selection",
            _trace.summarize_text_candidates(text_hits),
        )
        trace.set(
            "candidates_image_before_selection",
            _trace.summarize_image_candidates(image_hits),
        )

    with trace.time("merge_sort_fusion_ms"):
        hits = sorted(text_hits + image_hits, key=lambda h: h["score"], reverse=True)

    logger.info(
        "Direct context: %d text + %d image hits (query=%r, doc_filter=%s, source_type=%s, cross_source=%s)",
        len(text_hits), len(image_hits), query[:80], doc_filter, source_type, query_wants_cross_source,
    )
    return _build_context(hits, processed_query, model, temperature, max_tokens, trace=trace)
