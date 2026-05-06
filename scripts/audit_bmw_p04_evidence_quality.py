#!/usr/bin/env python3
"""Phase 0 evidence-quality audit for the BMW p04 diagnostic.

This is a read-only follow-up to ``scripts/diagnose_bmw_p04.py``. The live
trace classified p04 as ``generation`` because one loose brand-term match
reached final context. This audit checks the assumption behind that rule:
whether the matching final-context chunk is actually answer-bearing evidence.

It does not change retrieval behavior, embeddings, prompts, schema, or raw
chunk text. It connects to Postgres over TCP host=127.0.0.1 through the shared
Phase 0 helpers and writes a separate evidence-quality report:

    data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.md
    data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _phase0_utils import ensure_venv, now_iso, open_db_connection, phase0_baseline_dir  # noqa: E402

ensure_venv()

ROOT = Path(__file__).resolve().parent.parent
DIAG_PATH = ROOT / "data" / "eval" / "phase0_baseline" / "bmw_p04_diagnostic.json"

EXPANDED_TERMS = [
    "Konzernmarken",
    "Markenportfolio",
    "Marken des BMW Group",
    "Marken der BMW Group",
    "BMW Group im Überblick",
    "Organisation und Geschäftsmodell",
    "Segment Automobile",
    "Segment Motorräder",
    "Segment Finanzdienstleistungen",
    "BMW Motorrad",
    "Motorräder",
    "MINI gesamt",
    "Rolls-Royce gesamt",
    "Markteinführungen",
    "Auslieferungen MINI",
    "Auslieferungen von BMW Motorrädern",
]

# Reviewer labels from full-text inspection. Labels are intentionally limited
# to the Phase 0 evidence-audit vocabulary requested by the user.
LABELS: dict[int, tuple[str, str]] = {
    36806: (
        "garbled_or_extraction_noise",
        "Supervisory-board/navigation fragment; not BMW portfolio evidence.",
    ),
    36846: (
        "weak_keyword_match",
        "Board photo caption; 'Kunde, Marken, Vertrieb' is an executive remit, not the requested list.",
    ),
    36854: (
        "garbled_or_extraction_noise",
        "Supervisory-board/mandate text with extraction noise; no answer-bearing portfolio content.",
    ),
    36880: (
        "toc_or_index_only",
        "Table-of-contents page. It reached final context but only points to report sections.",
    ),
    36980: (
        "weak_keyword_match",
        "Market overview for international automobile/motorcycle markets, not BMW Group brands/business units.",
    ),
    37032: (
        "answer_bearing",
        "Substantive MINI and Rolls-Royce section text; partial evidence for the brand list.",
    ),
    37033: (
        "answer_bearing",
        "MINI and Rolls-Royce delivery table; partial evidence for the brand list.",
    ),
    37039: (
        "answer_bearing",
        "BMW Motorrad segment introduction; partial evidence, but embedding is NULL.",
    ),
    37040: (
        "answer_bearing",
        "BMW Motorrad market launches/deliveries text; partial evidence for business/brand coverage.",
    ),
    37041: (
        "answer_bearing",
        "BMW motorcycle deliveries / markets table; partial evidence for the Motorrad business.",
    ),
    37047: (
        "answer_bearing",
        "BMW Motorrad new-model discussion; partial evidence for the Motorrad business.",
    ),
    37106: (
        "weak_keyword_match",
        "False positive from 'Minimum Safeguards' matching the loose '%MINI%' term.",
    ),
    37291: (
        "weak_keyword_match",
        "Automobile/motorcycle market forecast context, not BMW Group portfolio evidence.",
    ),
    37300: (
        "weak_keyword_match",
        "Internal-control/risk-management section, not portfolio evidence.",
    ),
    37418: (
        "weak_keyword_match",
        "Internal-control section, not portfolio evidence.",
    ),
    37998: (
        "toc_or_index_only",
        "TCFD/NFE index link list, not substantive portfolio evidence.",
    ),
    38050: (
        "weak_keyword_match",
        "Contact/web-link page lists brand websites but does not answer the full p04 request.",
    ),
}


def _clean_preview(text: str | None, limit: int = 260) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned[:limit]


def _trace_maps(diag: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    trace = ((diag.get("retrieval") or {}).get("trace") or {})
    text_candidates = trace.get("candidates_text_before_selection") or []
    final_context = trace.get("final_context_chunks") or []
    cand_map: dict[int, dict[str, Any]] = {}
    for rank, cand in enumerate(text_candidates, start=1):
        cid = cand.get("chunk_id")
        if cid is not None:
            cand_map[int(cid)] = {
                "rank": rank,
                "score": cand.get("score"),
                "candidate": cand,
            }
    ctx_map: dict[int, dict[str, Any]] = {}
    for item in final_context:
        cid = item.get("chunk_id")
        if cid is not None:
            ctx_map[int(cid)] = item
    return cand_map, ctx_map


def _fetch_chunks(cur, ids: list[int]) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT id, page, chunk_type,
               (embedding IS NOT NULL) AS has_embedding,
               meta->>'embedding_error' AS embedding_error,
               meta->>'heading_path' AS heading_path,
               meta->>'element_type' AS element_type,
               char_length(COALESCE(content_text, '')) AS content_chars,
               content_text
        FROM rag_chunks
        WHERE id = ANY(%s)
        ORDER BY page, id;
        """,
        (ids,),
    )
    cols = [d.name for d in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fetch_expanded_matches(cur, doc_id: str) -> list[dict[str, Any]]:
    where = " OR ".join(["content_text ILIKE %s"] * len(EXPANDED_TERMS))
    cur.execute(
        f"""
        SELECT id, page, chunk_type,
               (embedding IS NOT NULL) AS has_embedding,
               meta->>'embedding_error' AS embedding_error,
               char_length(COALESCE(content_text, '')) AS content_chars,
               LEFT(content_text, 320) AS content_preview
        FROM rag_chunks
        WHERE doc_id = %s
          AND ({where})
        ORDER BY page, id;
        """,
        [doc_id] + [f"%{term}%" for term in EXPANDED_TERMS],
    )
    cols = [d.name for d in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fetch_neighbor_pages(cur, doc_id: str, pages: list[int]) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT id, page, chunk_type,
               (embedding IS NOT NULL) AS has_embedding,
               meta->>'embedding_error' AS embedding_error,
               char_length(COALESCE(content_text, '')) AS content_chars,
               LEFT(content_text, 280) AS content_preview
        FROM rag_chunks
        WHERE doc_id = %s
          AND page = ANY(%s)
        ORDER BY page, id;
        """,
        (doc_id, pages),
    )
    cols = [d.name for d in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def build_payload() -> dict[str, Any]:
    diag = json.loads(DIAG_PATH.read_text(encoding="utf-8"))
    doc_id = diag["doc_id"]
    original_ids = [int(c["id"]) for c in diag.get("matching_chunks") or []]
    cand_map, ctx_map = _trace_maps(diag)

    with open_db_connection() as conn, conn.cursor() as cur:
        chunks = _fetch_chunks(cur, original_ids)
        expanded = _fetch_expanded_matches(cur, doc_id)
        neighbor_pages = [37, 38, 39, 66, 69, 70, 71, 72]
        neighbors = _fetch_neighbor_pages(cur, doc_id, neighbor_pages)

    labelled: list[dict[str, Any]] = []
    for chunk in chunks:
        cid = int(chunk["id"])
        label, note = LABELS.get(
            cid,
            ("unclear", "No manual evidence-quality label was assigned."),
        )
        cand = cand_map.get(cid)
        ctx = ctx_map.get(cid)
        labelled.append(
            {
                "chunk_id": cid,
                "page": chunk["page"],
                "chunk_type": chunk["chunk_type"],
                "has_embedding": bool(chunk["has_embedding"]),
                "embedding_error": chunk["embedding_error"],
                "content_chars": chunk["content_chars"],
                "label": label,
                "label_note": note,
                "preview": _clean_preview(chunk.get("content_text")),
                "in_retrieval_candidates": cand is not None,
                "rank_in_candidates": cand.get("rank") if cand else None,
                "score_in_candidates": cand.get("score") if cand else None,
                "in_final_context": cid in ctx_map,
                "order_in_final_context": (
                    ctx.get("order_in_context") if ctx else None
                ),
            }
        )

    answer_bearing = [c for c in labelled if c["label"] == "answer_bearing"]
    answer_bearing_embedded = [c for c in answer_bearing if c["has_embedding"]]
    answer_bearing_candidates = [
        c for c in answer_bearing_embedded if c["in_retrieval_candidates"]
    ]
    answer_bearing_final = [c for c in answer_bearing if c["in_final_context"]]
    final_matched = [c for c in labelled if c["in_final_context"]]

    expanded_ids = {int(c["id"]) for c in expanded}
    expanded_intersect_candidates = sorted(expanded_ids & set(cand_map))
    expanded_intersect_final = sorted(expanded_ids & set(ctx_map))

    classification = "mixed_failure"
    explanation = (
        "The live trace's mechanical classification was generation, but the "
        "only original brand-term match in final context was chunk 36880, a "
        "table-of-contents chunk. True answer-bearing partial evidence exists "
        "in embedded chunks 37032, 37033, 37040, 37041, and 37047, but none "
        "of those reached retrieval candidates or final context. Chunk 37039 "
        "is also answer-bearing for BMW Motorrad but has a NULL embedding. "
        "The corrected substantive classification is therefore mixed: "
        "ranking/evidence-quality failure plus a missing-embedding component, "
        "with extraction noise on the BMW overview pages as a secondary risk."
    )

    return {
        "captured_at": now_iso(),
        "phase": "0 evidence-quality audit",
        "source_diagnostic": str(DIAG_PATH.relative_to(ROOT)),
        "p04_query": diag.get("p04_query"),
        "doc_id": doc_id,
        "mechanical_classification": diag.get("classification"),
        "corrected_classification": classification,
        "classification_explanation": explanation,
        "expanded_terms": EXPANDED_TERMS,
        "label_counts": {
            label: sum(1 for c in labelled if c["label"] == label)
            for label in sorted({c["label"] for c in labelled})
        },
        "answer_bearing_summary": {
            "total": len(answer_bearing),
            "embedded": len(answer_bearing_embedded),
            "in_retrieval_candidates": len(answer_bearing_candidates),
            "in_final_context": len(answer_bearing_final),
            "null_embedding_chunk_ids": [
                c["chunk_id"] for c in answer_bearing if not c["has_embedding"]
            ],
        },
        "chunk_36880_answer_bearing": False,
        "chunk_37039_matters": True,
        "final_matched_chunks": final_matched,
        "labelled_chunks": labelled,
        "expanded_match_count": len(expanded),
        "expanded_matches": [
            {
                **{k: v for k, v in item.items() if k != "content_preview"},
                "preview": _clean_preview(item.get("content_preview")),
                "in_retrieval_candidates": int(item["id"]) in cand_map,
                "rank_in_candidates": (
                    cand_map[int(item["id"])]["rank"]
                    if int(item["id"]) in cand_map
                    else None
                ),
                "in_final_context": int(item["id"]) in ctx_map,
            }
            for item in expanded
        ],
        "expanded_intersect_candidates": expanded_intersect_candidates,
        "expanded_intersect_final_context": expanded_intersect_final,
        "neighbor_pages": neighbor_pages,
        "neighbor_chunks": [
            {
                **{k: v for k, v in item.items() if k != "content_preview"},
                "preview": _clean_preview(item.get("content_preview")),
            }
            for item in neighbors
        ],
        "recommended_phase1_branch": (
            "Do not start Phase 1 from the mechanical generation label. After "
            "explicit approval, first run a targeted BMW missing-embedding "
            "backfill and re-run p04; if answer-bearing embedded chunks still "
            "do not rank, move to retrieval/evidence-quality work such as "
            "metadata prefixes or another approved retrieval branch."
        ),
    }


def render_md(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Phase 0 — BMW p04 Evidence-Quality Audit")
    lines.append("")
    lines.append(f"- **Captured at:** {payload['captured_at']}")
    lines.append(f"- **Source diagnostic:** `{payload['source_diagnostic']}`")
    lines.append(f"- **Mechanical classification:** `{payload['mechanical_classification']}`")
    lines.append(f"- **Corrected classification:** `{payload['corrected_classification']}`")
    lines.append("")
    lines.append("## Conclusion")
    lines.append("")
    lines.append(payload["classification_explanation"])
    lines.append("")
    lines.append("- **Chunk 36880 answer-bearing?** No. It is table-of-contents style evidence.")
    lines.append(
        "- **Chunk 37039 matters?** Yes. It is BMW Motorrad evidence, but has a NULL embedding."
    )
    lines.append(
        "- **Any true answer-bearing original brand-term chunk reached final context?** "
        f"{'Yes' if payload['answer_bearing_summary']['in_final_context'] else 'No'}."
    )
    lines.append("")

    lines.append("## Original 17 Matching Chunks")
    lines.append("")
    lines.append(
        "| chunk | page | emb | label | in_cand | rank | score | in_ctx | note |"
    )
    lines.append("|---:|---:|:---:|---|:---:|---:|---:|:---:|---|")
    for c in payload["labelled_chunks"]:
        rank = c["rank_in_candidates"] if c["rank_in_candidates"] is not None else "—"
        score = (
            f"{float(c['score_in_candidates']):.4f}"
            if c["score_in_candidates"] is not None
            else "—"
        )
        lines.append(
            "| {chunk_id} | {page} | {emb} | `{label}` | {cand} | {rank} | "
            "{score} | {ctx} | {note} |".format(
                chunk_id=c["chunk_id"],
                page=c["page"],
                emb="Y" if c["has_embedding"] else "N",
                label=c["label"],
                cand="Y" if c["in_retrieval_candidates"] else "N",
                rank=rank,
                score=score,
                ctx="Y" if c["in_final_context"] else "N",
                note=c["label_note"],
            )
        )
    lines.append("")

    lines.append("## Answer-Bearing Summary")
    lines.append("")
    s = payload["answer_bearing_summary"]
    lines.append(f"- answer-bearing original matches: {s['total']}")
    lines.append(f"- embedded answer-bearing matches: {s['embedded']}")
    lines.append(
        f"- answer-bearing matches in retrieval candidates: {s['in_retrieval_candidates']}"
    )
    lines.append(
        f"- answer-bearing matches in final context: {s['in_final_context']}"
    )
    lines.append(
        "- answer-bearing NULL-embedding chunk IDs: "
        + (", ".join(str(x) for x in s["null_embedding_chunk_ids"]) or "none")
    )
    lines.append("")

    lines.append("## Expanded Matcher")
    lines.append("")
    lines.append(
        "The expanded terms include `Konzernmarken`, `Markenportfolio`, "
        "`Marken des BMW Group`, `BMW Group im Überblick`, segment headings, "
        "and BMW Motorrad / MINI / Rolls-Royce table phrases."
    )
    lines.append("")
    lines.append(f"- expanded matches: {payload['expanded_match_count']}")
    lines.append(
        "- expanded matches in retrieval candidates: "
        + (", ".join(str(x) for x in payload["expanded_intersect_candidates"]) or "none")
    )
    lines.append(
        "- expanded matches in final context: "
        + (", ".join(str(x) for x in payload["expanded_intersect_final_context"]) or "none")
    )
    lines.append("")
    lines.append("| chunk | page | emb | in_cand | rank | in_ctx | preview |")
    lines.append("|---:|---:|:---:|:---:|---:|:---:|---|")
    for c in payload["expanded_matches"]:
        rank = c["rank_in_candidates"] if c["rank_in_candidates"] is not None else "—"
        lines.append(
            "| {id} | {page} | {emb} | {cand} | {rank} | {ctx} | {preview} |".format(
                id=c["id"],
                page=c["page"],
                emb="Y" if c["has_embedding"] else "N",
                cand="Y" if c["in_retrieval_candidates"] else "N",
                rank=rank,
                ctx="Y" if c["in_final_context"] else "N",
                preview=(c["preview"] or "").replace("|", "\\|"),
            )
        )
    lines.append("")

    lines.append("## Neighbor Pages Checked")
    lines.append("")
    lines.append(
        "Same-page chunks were checked for the overview/segment pages and the "
        "strongest brand-evidence pages: "
        + ", ".join(str(p) for p in payload["neighbor_pages"])
        + "."
    )
    lines.append("")
    lines.append("| chunk | page | emb | error | chars | preview |")
    lines.append("|---:|---:|:---:|---|---:|---|")
    for c in payload["neighbor_chunks"]:
        lines.append(
            "| {id} | {page} | {emb} | {err} | {chars} | {preview} |".format(
                id=c["id"],
                page=c["page"],
                emb="Y" if c["has_embedding"] else "N",
                err=c["embedding_error"] or "",
                chars=c["content_chars"],
                preview=(c["preview"] or "").replace("|", "\\|"),
            )
        )
    lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    lines.append(payload["recommended_phase1_branch"])
    lines.append("")
    lines.append(
        "Stop here for Phase 0. No backfill, retrieval change, metadata prefix, "
        "hybrid search, reranker, or generation prompt change was executed by this audit."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    payload = build_payload()
    out_dir = phase0_baseline_dir()
    json_path = out_dir / "bmw_p04_evidence_quality_audit.json"
    md_path = out_dir / "bmw_p04_evidence_quality_audit.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_md(payload), encoding="utf-8")
    print(f"[audit] wrote {md_path.relative_to(ROOT)}")
    print(f"[audit] wrote {json_path.relative_to(ROOT)}")
    print(f"[audit] corrected_classification: {payload['corrected_classification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
