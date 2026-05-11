"""RAG_TRACE flag, retrieval-trace JSONL writer, and per-request timing helpers.

Defaults preserve production response behavior:
- ``RAG_TRACE=false`` (default) — no JSONL writes; record is not populated;
  only lightweight timings are collected for the structured-log one-liner.
- ``RAG_TRACE=true`` — populate the full per-request record and append it to
  ``RAG_TRACE_PATH`` (default ``/data/rag-traces/retrieval.jsonl``).

Trace records contain per-request retrieval evidence: parsed routing, the
candidate hit lists *before* selection (text + image), the chunks that reach
final context, the sources/images emitted in the suffix, and per-stage
timings. They never log full chat history beyond the current user turn,
API keys, or other secrets.

The ``RetrievalTrace`` class also exposes ``force_populate`` so the
``/v1/diagnostic/retrieval`` helper endpoint can return a fully populated
record without flipping the global flag — that path never persists to disk.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "")
    if not raw:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


RAG_TRACE_ENABLED: bool = _parse_bool_env("RAG_TRACE", default=False)
RAG_TRACE_PATH: str = os.getenv("RAG_TRACE_PATH", "/data/rag-traces/retrieval.jsonl")
RAG_TRACE_PREVIEW_TEXT: int = int(os.getenv("RAG_TRACE_PREVIEW_TEXT", "300"))
RAG_TRACE_PREVIEW_CAPTION: int = int(os.getenv("RAG_TRACE_PREVIEW_CAPTION", "200"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class RetrievalTrace:
    """Per-request trace + timing accumulator."""

    __slots__ = ("req_id", "timings_ms", "populate", "persist", "record")

    def __init__(
        self,
        req_id: str,
        model_requested: str,
        raw_user_query: str,
        *,
        force_populate: bool = False,
    ) -> None:
        self.req_id = req_id
        self.timings_ms: dict[str, float] = {}
        # populate controls whether candidate/context data is collected.
        # persist controls whether the record is appended to JSONL.
        self.populate: bool = RAG_TRACE_ENABLED or force_populate
        self.persist: bool = RAG_TRACE_ENABLED
        if self.populate:
            self.record: dict | None = {
                "req_id": req_id,
                "timestamp": _now_iso(),
                "model_requested": model_requested,
                "raw_user_query": (raw_user_query or "")[:1000],
            }
        else:
            self.record = None

    @property
    def enabled(self) -> bool:
        """Truthy when call sites should populate full record fields."""
        return self.populate

    @contextmanager
    def time(self, key: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.timings_ms[key] = round((time.perf_counter() - t0) * 1000.0, 2)

    def add_timing(self, key: str, ms: float) -> None:
        self.timings_ms[key] = round(ms, 2)

    def set(self, key: str, value) -> None:
        if self.populate and self.record is not None:
            self.record[key] = value

    def setdefault(self, key: str, default):
        if self.populate and self.record is not None:
            return self.record.setdefault(key, default)
        return default

    def finalize_timings(self) -> None:
        if self.populate and self.record is not None:
            self.record["timings_ms"] = dict(self.timings_ms)

    def write(self) -> bool:
        """Append the record to RAG_TRACE_PATH. Returns True on success."""
        if not self.persist or self.record is None:
            return False
        self.finalize_timings()
        try:
            os.makedirs(os.path.dirname(RAG_TRACE_PATH) or ".", exist_ok=True)
            with open(RAG_TRACE_PATH, "a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(self.record, ensure_ascii=False, default=str) + "\n"
                )
            return True
        except OSError:
            return False

    def timings_one_liner(self) -> str:
        order = (
            ("embed", "query_embedding_ms"),
            ("sql", "vector_sql_total_ms"),
            ("fusion", "merge_sort_fusion_ms"),
            ("build", "context_assembly_ms"),
            ("total", "total_retrieval_before_llm_ms"),
        )
        bits: list[str] = []
        for short, full in order:
            v = self.timings_ms.get(full)
            if v is not None:
                bits.append(f"{short}={int(v)}")
        return " ".join(bits) + " ms" if bits else ""


# ---------------------------------------------------------------------------
# Diagnostic-only enrichment (Stage 3.0 — observation, never ranking input)
# ---------------------------------------------------------------------------
# The fields produced here describe each candidate; they are written into the
# trace record so future analysis (reranker design, metadata-aware penalties,
# hybrid debugging) can see *why* a chunk surfaced or was dropped. They are
# explicitly NOT consulted by candidate selection, image filtering, the
# cross-doc-id guard, context packing, or any other ranking decision.

# Heading-path substring markers, lowercased. Inhaltsverzeichnis is the
# canonical German front-matter TOC; Index / Stichwortverzeichnis / Impressum
# are back-matter markers in German publishing conventions. Matching is
# heuristic — substring hits in body text count as false positives.
_HEADING_PATH_FRONT_MARKERS: tuple[str, ...] = ("inhaltsverzeichnis",)
_HEADING_PATH_BACK_MARKERS: tuple[str, ...] = (
    "stichwortverzeichnis",
    "impressum",
    "index",  # last so 'inhaltsindex' / 'sachindex' still resolve sensibly
)


def _coerce_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _heading_path_to_text(value) -> str:
    """Reduce ``meta.heading_path`` to a single lowercase string for marker
    matching. The schema stores it as either a list of breadcrumb segments or
    a single string. Anything else collapses to empty."""
    if isinstance(value, list):
        return " > ".join(str(v) for v in value if v).lower()
    if isinstance(value, str):
        return value.lower()
    return ""


def _diagnostic_flags(
    page,
    doc_pages,
    heading_path,
) -> tuple[bool, bool, list[str]]:
    """Compute ``front_matter_like`` / ``back_matter_like`` and the reason list.

    Booleans are diagnostic-only. They never feed retrieval ranking or
    context packing. ``page`` and ``doc_pages`` are passed through
    ``_coerce_int`` so DB rows with int-as-text values stay sensible.
    """
    reasons: list[str] = []
    front = False
    back = False

    p = _coerce_int(page)
    dp = _coerce_int(doc_pages)
    if dp is not None and dp <= 0:
        dp = None

    if p is not None:
        if p <= 10:
            front = True
            reasons.append("page_in_first_10")
        if dp is not None:
            if p >= max(1, dp - 10):
                back = True
                reasons.append("page_in_last_10")
        elif p >= 320:
            back = True
            reasons.append("page_fallback_gte_320")

    hp_text = _heading_path_to_text(heading_path)
    if hp_text:
        toc_hit = False
        if any(m in hp_text for m in _HEADING_PATH_FRONT_MARKERS):
            front = True
            toc_hit = True
        if any(m in hp_text for m in _HEADING_PATH_BACK_MARKERS):
            back = True
            toc_hit = True
        if toc_hit and "heading_path_contains_toc" not in reasons:
            reasons.append("heading_path_contains_toc")

    return front, back, reasons


def _enrich_with_diagnostics(out: dict, hit: dict, *, kind: str) -> None:
    """Attach diagnostic-only fields to ``out``.

    ``kind`` selects which content length field to populate:
        - ``"text"``     → ``content_length`` from ``content_text``
        - ``"image"``    → ``caption_length`` from ``caption``
        - ``"auto"``     → use ``hit['chunk_type']`` to choose

    All diagnostic fields default sanely (``None``/``False`` / empty list)
    when the source data is missing. The function never raises on partial
    rows.
    """
    meta = hit.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    doc_filename = hit.get("doc_filename") or ""
    if not isinstance(doc_filename, str):
        doc_filename = ""

    is_rss = doc_filename.startswith("http")
    is_pdf = (not is_rss) and doc_filename.lower().endswith(".pdf")

    doc_pages_raw = hit.get("doc_pages")
    doc_pages = _coerce_int(doc_pages_raw)
    if doc_pages is not None and doc_pages <= 0:
        doc_pages = None
    doc_lang = hit.get("doc_lang")
    if doc_lang is not None and not isinstance(doc_lang, str):
        doc_lang = str(doc_lang)

    heading_path = meta.get("heading_path")
    front, back, reasons = _diagnostic_flags(
        hit.get("page"), doc_pages_raw, heading_path
    )

    chunk_type = hit.get("chunk_type")
    if kind == "auto":
        kind_resolved = "image" if chunk_type == "image" else "text"
    else:
        kind_resolved = kind
    if kind_resolved == "image":
        out["caption_length"] = len(hit.get("caption") or "")
    else:
        out["content_length"] = len(hit.get("content_text") or "")

    out["split_strategy"] = meta.get("split_strategy")
    out["bbox_present"] = meta.get("bbox") is not None
    out["page_size_present"] = meta.get("page_size") is not None
    out["meta_source"] = meta.get("source")
    out["content_type"] = meta.get("content_type")
    out["is_pdf"] = bool(is_pdf)
    out["is_rss"] = bool(is_rss)
    out["meta_embedding_error"] = meta.get("embedding_error")
    out["doc_pages"] = doc_pages
    out["doc_lang"] = doc_lang
    out["front_matter_like"] = front
    out["back_matter_like"] = back
    out["front_or_back_matter_reason"] = reasons


def summarize_text_candidates(
    hits, preview_chars: int | None = None
) -> list[dict]:
    """Snapshot text-candidate hits for the trace record."""
    n = preview_chars if preview_chars is not None else RAG_TRACE_PREVIEW_TEXT
    out: list[dict] = []
    for h in hits:
        meta = h.get("meta") or {}
        score = float(h.get("score", 0.0))
        rec = {
            "chunk_id": h.get("id"),
            "doc_id": str(h["doc_id"]) if h.get("doc_id") is not None else None,
            "filename": h.get("doc_filename"),
            "page": h.get("page"),
            "chunk_type": h.get("chunk_type"),
            "score": round(score, 4),
            "distance": round(1.0 - score, 4),
            "meta_source": meta.get("source"),
            "heading_path": meta.get("heading_path"),
            "element_type": meta.get("element_type"),
            "content_preview": (h.get("content_text") or "")[:n],
        }
        _enrich_with_diagnostics(rec, h, kind="text")
        out.append(rec)
    return out


def summarize_image_candidates(
    hits, preview_chars: int | None = None
) -> list[dict]:
    """Snapshot image-candidate hits for the trace record.

    ``dropped_by_*`` fields are populated by ``_build_context`` after the
    image-filter / cross-doc-id guard runs.
    """
    n = preview_chars if preview_chars is not None else RAG_TRACE_PREVIEW_CAPTION
    out: list[dict] = []
    for h in hits:
        meta = h.get("meta") or {}
        score = float(h.get("score", 0.0))
        rec = {
            "chunk_id": h.get("id"),
            "doc_id": str(h["doc_id"]) if h.get("doc_id") is not None else None,
            "filename": h.get("doc_filename"),
            "page": h.get("page"),
            "score": round(score, 4),
            "caption_preview": (h.get("caption") or "")[:n],
            "asset_path": h.get("asset_path"),
            "heading_path": meta.get("heading_path"),
            "element_type": meta.get("element_type"),
            "dropped_by_image_score_min": False,
            "dropped_by_cross_doc_id_guard": False,
        }
        _enrich_with_diagnostics(rec, h, kind="image")
        out.append(rec)
    return out


def enrich_final_context_chunk(rec: dict, hit: dict) -> None:
    """Public helper used by ``context._build_context``.

    Mutates ``rec`` in place, adding the same diagnostic fields surfaced on
    candidate lists. ``hit`` is the raw DB row that produced ``rec``.
    """
    _enrich_with_diagnostics(rec, hit, kind="auto")
