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


def summarize_text_candidates(
    hits, preview_chars: int | None = None
) -> list[dict]:
    """Snapshot text-candidate hits for the trace record."""
    n = preview_chars if preview_chars is not None else RAG_TRACE_PREVIEW_TEXT
    out: list[dict] = []
    for h in hits:
        meta = h.get("meta") or {}
        score = float(h.get("score", 0.0))
        out.append(
            {
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
        )
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
        score = float(h.get("score", 0.0))
        out.append(
            {
                "chunk_id": h.get("id"),
                "doc_id": str(h["doc_id"]) if h.get("doc_id") is not None else None,
                "filename": h.get("doc_filename"),
                "page": h.get("page"),
                "score": round(score, 4),
                "caption_preview": (h.get("caption") or "")[:n],
                "asset_path": h.get("asset_path"),
                "dropped_by_image_score_min": False,
                "dropped_by_cross_doc_id_guard": False,
            }
        )
    return out
