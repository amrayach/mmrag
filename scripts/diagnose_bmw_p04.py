#!/usr/bin/env python3
"""Phase 0.4 — BMW p04 list-completeness targeted diagnostic.

Resolves the expected source for prompt ``p04`` from
``data/eval/prompts.json`` (no hard-coded filename), greps the brand-list
strings *inside* that document via parenthesized ``OR`` so the OR clauses
cannot escape the ``doc_id`` filter, runs the production retrieval path
for the p04 prompt via the rag-gateway diagnostic endpoint, then classifies
the failure as one of:

    missing_chunk   — the brand-list page is not in rag_chunks
    missing_embedding — the chunk exists but embedding is NULL
    low_rank        — exists, embedded, never makes it into top-k candidates
    context_packing — reaches candidates but is dropped during fusion / guards
    generation      — reaches final context; failure is downstream of retrieval
    unknown_due_to_insufficient_evidence
                    — retrieval could not be invoked, so rank/context evidence
                      is unavailable

Outputs:
    data/eval/phase0_baseline/bmw_p04_diagnostic.md
    data/eval/phase0_baseline/bmw_p04_diagnostic.json

Usage:
    python scripts/diagnose_bmw_p04.py
    python scripts/diagnose_bmw_p04.py --gateway http://127.0.0.1:56155 --no-retrieval

The retrieval step requires rag-gateway to be running with ``RAG_TRACE=true``.
With ``--no-retrieval`` the script still produces the chunk inventory but flags
the retrieval section as skipped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _phase0_utils import (  # noqa: E402
    ensure_venv,
    open_db_connection,
    phase0_baseline_dir,
    now_iso,
    gateway_url,
)

ensure_venv()

PROMPTS_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "prompts.json"

BRAND_LIST_TERMS = [
    "MINI",
    "Rolls",
    "Rolls-Royce",
    "Motorrad",
    "Marken",
    "Konzernmarken",
    "BMW Group brands",
]


def resolve_p04_doc(prompts: dict) -> tuple[str, list[str], dict]:
    """Return (filename_to_use, all_candidates, prompt_record)."""
    matches = [p for p in prompts["prompts"] if p["id"].startswith("p04")]
    if not matches:
        raise SystemExit(
            "FATAL: prompts.json has no 'p04' entry; cannot resolve expected source."
        )
    p04 = matches[0]
    sources = p04.get("expects_sources_from") or []
    if not sources:
        raise SystemExit(
            "FATAL: p04.expects_sources_from is empty; cannot resolve expected source."
        )
    pdf_sources = [s for s in sources if s.lower().endswith(".pdf")]
    if len(pdf_sources) == 1:
        return pdf_sources[0], list(sources), p04
    if len(sources) == 1:
        return sources[0], list(sources), p04
    raise SystemExit(
        "FATAL: p04.expects_sources_from has multiple PDF candidates "
        f"({sources}); refusing to guess. Edit prompts.json to disambiguate "
        "or pass a single PDF source."
    )


def lookup_doc_id(cur, filename: str) -> str | None:
    cur.execute(
        "SELECT doc_id FROM rag_docs WHERE filename = %s LIMIT 1;", (filename,)
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def grep_brand_list(cur, doc_id: str) -> list[dict]:
    sql = """
        SELECT id, page, chunk_type,
               (embedding IS NOT NULL) AS has_embedding,
               meta->>'embedding_error' AS embedding_error,
               meta->>'heading_path'    AS heading_path,
               meta->>'element_type'    AS element_type,
               char_length(COALESCE(content_text, '')) AS content_chars,
               LEFT(content_text, 300)  AS content_preview
        FROM rag_chunks
        WHERE doc_id = %s
          AND (
            content_text ILIKE %s
            OR content_text ILIKE %s
            OR content_text ILIKE %s
            OR content_text ILIKE %s
            OR content_text ILIKE %s
            OR content_text ILIKE %s
            OR content_text ILIKE %s
          )
        ORDER BY page, id;
    """
    params = [doc_id] + [f"%{t}%" for t in BRAND_LIST_TERMS]
    cur.execute(sql, params)
    cols = [d.name for d in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def run_production_retrieval(
    gateway: str, p04_query: str, model: str | None
) -> dict:
    """POST to /v1/diagnostic/retrieval (added in Phase 0.1) which calls the
    same shared retrieval function as /v1/chat/completions but skips the LLM.
    """
    import requests  # type: ignore[import-not-found]

    payload = {
        "messages": [{"role": "user", "content": p04_query}],
        "stream": False,
    }
    if model:
        payload["model"] = model
    url = f"{gateway.rstrip('/')}/v1/diagnostic/retrieval"
    r = requests.post(url, json=payload, timeout=120)
    if r.status_code == 404:
        raise RuntimeError(
            "gateway diagnostic endpoint is unavailable; rebuild/restart "
            "rag-gateway with RAG_TRACE=true before running full retrieval "
            "diagnostics"
        )
    r.raise_for_status()
    return r.json()


def cross_reference(
    matching_chunks: list[dict], retrieval: dict
) -> tuple[list[dict], dict | None, dict | None]:
    """Annotate matching chunks with retrieval status. Returns
    (annotated, headline_chunk, headline_in_context_chunk).
    The headline chunk is the highest-ranked candidate among matches; the
    in-context chunk is the highest-ranked match that reached final context.
    """
    trace = retrieval.get("trace") if retrieval else None
    text_cands = (trace or {}).get("candidates_text_before_selection") or []
    final_ctx = (trace or {}).get("final_context_chunks") or []
    cand_by_id = {
        c.get("chunk_id"): (rank, c) for rank, c in enumerate(text_cands, start=1)
    }
    final_by_id = {c.get("chunk_id"): (i, c) for i, c in enumerate(final_ctx)}

    annotated: list[dict] = []
    headline_cand: dict | None = None
    headline_in_ctx: dict | None = None
    for m in matching_chunks:
        chunk_id = m.get("id")
        in_cand = cand_by_id.get(chunk_id)
        in_ctx = final_by_id.get(chunk_id)
        rec = {
            "chunk_id": chunk_id,
            "page": m.get("page"),
            "chunk_type": m.get("chunk_type"),
            "exists_in_rag_chunks": True,
            "has_embedding": bool(m.get("has_embedding")),
            "embedding_error": m.get("embedding_error"),
            "heading_path": m.get("heading_path"),
            "element_type": m.get("element_type"),
            "content_chars": m.get("content_chars"),
            "content_preview": m.get("content_preview"),
            "in_retrieval_candidates": in_cand is not None,
            "rank_in_candidates": (in_cand[0] if in_cand else None),
            "score_in_candidates": (
                in_cand[1].get("score") if in_cand else None
            ),
            "in_final_context": in_ctx is not None,
            "order_in_final_context": (in_ctx[0] if in_ctx else None),
        }
        annotated.append(rec)
        if rec["in_retrieval_candidates"]:
            if headline_cand is None or (
                rec["rank_in_candidates"] is not None
                and rec["rank_in_candidates"] < (headline_cand.get("rank_in_candidates") or 1_000_000)
            ):
                headline_cand = rec
        if rec["in_final_context"] and headline_in_ctx is None:
            headline_in_ctx = rec
    return annotated, headline_cand, headline_in_ctx


def classify(
    matching_chunks: list[dict],
    annotated: list[dict],
    retrieval_skipped: bool,
    retrieval_error: str | None = None,
) -> tuple[str, str]:
    """Return (classification, one_paragraph_explanation)."""
    if not matching_chunks:
        return (
            "missing_chunk",
            "No chunks in the resolved p04 document matched any of the "
            "brand-list terms. For this Phase 0 diagnostic, that means the "
            "likely brand-list evidence is not visible in rag_chunks and the "
            "failure should be treated as a chunking / extraction gap until "
            "manual inspection proves the term set is insufficient.",
        )

    has_embed_chunks = [c for c in annotated if c["has_embedding"]]
    if not has_embed_chunks:
        return (
            "missing_embedding",
            f"All {len(annotated)} matching brand-list chunk(s) exist in "
            "rag_chunks but have NULL embeddings — they are silently excluded "
            "from retrieval by the production WHERE embedding IS NOT NULL "
            "filter. Phase 1 should re-embed these chunks before any "
            "retrieval-side changes.",
        )

    if retrieval_skipped:
        detail = (
            f" Retrieval error: {retrieval_error}."
            if retrieval_error
            else ""
        )
        return (
            "unknown_due_to_insufficient_evidence",
            f"{len(has_embed_chunks)} embedded brand-list chunk(s) exist; "
            "retrieval rank/final-context evidence is unavailable. Re-run "
            "without --no-retrieval after rag-gateway has been rebuilt and "
            f"started with RAG_TRACE=true to obtain the final classification.{detail}",
        )

    in_cand = [c for c in annotated if c["has_embedding"] and c["in_retrieval_candidates"]]
    in_ctx = [c for c in annotated if c["has_embedding"] and c["in_final_context"]]

    if not in_cand:
        return (
            "low_rank",
            f"{len(has_embed_chunks)} brand-list chunk(s) are embedded but "
            "none ranked into the production retrieval candidates for the p04 "
            "query. The dense embedding similarity is insufficient to surface "
            "these chunks in top-k. Phase 1 candidates: deterministic PDF "
            "index prefixes (heading_path/page/element_type), hybrid retrieval, "
            "or a reranker.",
        )

    if in_cand and not in_ctx:
        return (
            "context_packing",
            f"{len(in_cand)} brand-list chunk(s) reached retrieval candidates "
            "but were dropped before final context (likely by merge/sort/fusion, "
            "image guard, or the cross-doc-id guard). Phase 1 candidates: tune "
            "top-k slot allocation per source, image guard thresholds, and the "
            "+0.10 image-score boost.",
        )

    return (
        "generation",
        f"{len(in_ctx)} brand-list chunk(s) reached final context for p04. "
        "The list-completeness failure is downstream of retrieval — likely a "
        "prompt or generator concern. Out of scope for retrieval upgrades.",
    )


def render_md(payload: dict) -> str:
    lines: list[str] = []
    lines.append("# Phase 0.4 — BMW p04 targeted diagnostic")
    lines.append("")
    lines.append(f"- **Captured at:** {payload['captured_at']}")
    lines.append(f"- **Resolved expected doc:** `{payload['expected_doc']}`")
    lines.append(f"- **All candidates from prompts.json:** {payload['expected_candidates']}")
    lines.append(f"- **doc_id:** `{payload.get('doc_id') or '<not found>'}`")
    lines.append(f"- **Search terms:** `{payload['brand_list_terms']}`")
    lines.append(f"- **Matching chunks:** {len(payload['matching_chunks'])}")
    lines.append(f"- **Retrieval attempted:** {payload['retrieval_attempted']}")
    lines.append(f"- **Retrieval evidence available:** {not payload['retrieval_skipped']}")
    if payload.get("retrieval_error"):
        lines.append(f"- **Retrieval error:** {payload['retrieval_error']}")
    lines.append("")

    lines.append("## Classification")
    lines.append("")
    lines.append(f"**`{payload['classification']}`**")
    lines.append("")
    lines.append(payload["classification_explanation"])
    lines.append("")

    lines.append("## Matching brand-list chunks")
    lines.append("")
    if not payload["matching_chunks"]:
        lines.append("_No matches found in this document for any brand-list term._")
        lines.append("")
    else:
        lines.append(
            "| chunk_id | page | type | has_emb | embedding_error | "
            "heading_path | element_type | chars | in_cand | rank | score | "
            "in_ctx | order |"
        )
        lines.append(
            "|---:|---:|---|:---:|---|---|---|---:|:---:|---:|---:|:---:|---:|"
        )
        for r in payload["annotated"]:
            lines.append(
                "| {chunk_id} | {page} | {chunk_type} | {has} | {err} | "
                "{hp} | {et} | {chars} | {ic} | {rank} | {score} | "
                "{ix} | {ord} |".format(
                    chunk_id=r["chunk_id"],
                    page=r["page"],
                    chunk_type=r["chunk_type"],
                    has="Y" if r["has_embedding"] else "N",
                    err=r["embedding_error"] or "",
                    hp=(r["heading_path"] or "")[:40],
                    et=(r["element_type"] or "")[:18],
                    chars=r["content_chars"] or 0,
                    ic="Y" if r["in_retrieval_candidates"] else "N",
                    rank=r["rank_in_candidates"] if r["rank_in_candidates"] is not None else "—",
                    score=(
                        f"{r['score_in_candidates']:.4f}"
                        if r["score_in_candidates"] is not None
                        else "—"
                    ),
                    ix="Y" if r["in_final_context"] else "N",
                    ord=r["order_in_final_context"] if r["order_in_final_context"] is not None else "—",
                )
            )
        lines.append("")
        lines.append("### Content previews")
        lines.append("")
        for r in payload["annotated"]:
            lines.append(f"- **chunk {r['chunk_id']}** (page {r['page']}):")
            preview = (r["content_preview"] or "").strip().replace("\n", " ")
            lines.append(f"  > {preview[:300]}")
        lines.append("")

    lines.append("## Production retrieval summary")
    lines.append("")
    if payload.get("retrieval_error"):
        lines.append(f"_Retrieval failed: {payload['retrieval_error']}_")
    elif payload["retrieval_skipped"]:
        lines.append("_Retrieval was skipped (`--no-retrieval`)._")
    else:
        retr = payload["retrieval"] or {}
        trace = retr.get("trace") or {}
        ctx_text = (trace.get("candidates_text_before_selection") or [])
        ctx_img = (trace.get("candidates_image_before_selection") or [])
        final = trace.get("final_context_chunks") or []
        lines.append(
            f"- text candidates returned: {len(ctx_text)}, "
            f"image candidates returned: {len(ctx_img)}"
        )
        lines.append(
            f"- final context chunks: {len(final)} "
            f"(chars≈{trace.get('context_char_count', '?')})"
        )
        lines.append(f"- sources emitted: {retr.get('sources') or []}")
        lines.append("")
        lines.append("### Top text candidates")
        lines.append("")
        lines.append("| rank | chunk_id | page | filename | score | preview |")
        lines.append("|---:|---:|---:|---|---:|---|")
        for i, c in enumerate(ctx_text[:10]):
            preview = (c.get("content_preview") or "").strip().replace("\n", " ")[:80]
            lines.append(
                "| {i} | {ci} | {p} | {fn} | {s:.4f} | {prev} |".format(
                    i=i,
                    ci=c.get("chunk_id"),
                    p=c.get("page"),
                    fn=c.get("filename") or "",
                    s=float(c.get("score", 0.0)),
                    prev=preview,
                )
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gateway", default=gateway_url())
    p.add_argument(
        "--model",
        default=None,
        help="Override model; defaults to gateway DEFAULT_MODEL",
    )
    p.add_argument(
        "--no-retrieval",
        action="store_true",
        help="Skip the production retrieval call; only inventory the chunks",
    )
    args = p.parse_args()

    prompts = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    expected_doc, candidates, p04 = resolve_p04_doc(prompts)
    p04_query = p04["turns"][0]["user"]

    with open_db_connection() as conn, conn.cursor() as cur:
        doc_id = lookup_doc_id(cur, expected_doc)
        matching: list[dict] = []
        if doc_id:
            matching = grep_brand_list(cur, doc_id)

    retrieval: dict | None = None
    retrieval_error: str | None = None
    if not args.no_retrieval:
        try:
            retrieval = run_production_retrieval(
                args.gateway, p04_query, args.model
            )
        except Exception as exc:
            retrieval_error = f"{type(exc).__name__}: {exc}"

    annotated, headline_cand, headline_in_ctx = cross_reference(
        matching, retrieval or {}
    )
    classification, explanation = classify(
        matching,
        annotated,
        retrieval_skipped=args.no_retrieval or retrieval is None,
        retrieval_error=retrieval_error,
    )

    payload = {
        "captured_at": now_iso(),
        "phase": "0.4",
        "p04_query": p04_query,
        "expected_doc": expected_doc,
        "expected_candidates": candidates,
        "doc_id": doc_id,
        "brand_list_terms": BRAND_LIST_TERMS,
        "matching_chunks": matching,
        "annotated": annotated,
        "headline_candidate": headline_cand,
        "headline_in_context": headline_in_ctx,
        "retrieval_attempted": not args.no_retrieval,
        "retrieval_skipped": args.no_retrieval or retrieval is None,
        "retrieval_error": retrieval_error,
        "retrieval": retrieval,
        "classification": classification,
        "classification_explanation": explanation,
    }

    out_dir = phase0_baseline_dir()
    json_path = out_dir / "bmw_p04_diagnostic.json"
    md_path = out_dir / "bmw_p04_diagnostic.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    md_path.write_text(render_md(payload), encoding="utf-8")
    print(f"[diag] wrote {md_path.relative_to(Path.cwd())}", file=sys.stderr)
    print(f"[diag] wrote {json_path.relative_to(Path.cwd())}", file=sys.stderr)
    print(f"[diag] classification: {classification}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
