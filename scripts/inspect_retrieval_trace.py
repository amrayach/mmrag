#!/usr/bin/env python3
"""Stage 3.0 — Retrieval-trace inspector.

Pure file-reading + analysis: reads a ``retrieval.jsonl`` trace file, picks
the record matching ``--prompt-id`` (or the latest record if no filter), and
emits a Markdown + JSON inspection report under
``data/eval/trace_inspections/``.

It NEVER mutates the trace file, NEVER calls rag-gateway, and NEVER touches
the database. It is purely an analysis tool over the JSONL records that
Stage 3.0 instrumentation extended with diagnostic-only fields
(``front_matter_like``, ``back_matter_like``, ``heading_path``, ``element_type``,
``split_strategy``, ``bbox_present``, etc.).

Records produced before Stage 3.0 lack the new fields. The inspector handles
this gracefully — missing fields surface as ``-`` in tables and excluded
from coverage percentages.

Usage:
    python scripts/inspect_retrieval_trace.py \\
        --trace data/rag-traces/retrieval.jsonl \\
        --gold data/eval/gold_chunks.phase0.json \\
        --prompt-id p04

    python scripts/inspect_retrieval_trace.py \\
        --trace data/eval/runs/<run-dir>/traces/retrieval.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "data" / "eval" / "trace_inspections"
DEFAULT_PROMPTS_PATH = ROOT / "data" / "eval" / "prompts.json"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                print(
                    f"[inspector] WARN line {lineno}: invalid JSON: {exc}",
                    file=sys.stderr,
                )
    return records


def _load_gold(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for key, value in raw.items():
        if isinstance(value, dict) and "gold_chunk_ids" in value:
            out[key] = value
    return out


def _load_prompts(path: Path | None) -> dict[str, dict]:
    """Map both ``p04`` and ``p04_bmw_list_completeness`` style ids to the
    prompt record. Used to resolve a ``--prompt-id`` short code into a query
    for substring-matching traces."""
    if path is None or not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    prompts = raw.get("prompts", [])
    out: dict[str, dict] = {}
    for p in prompts:
        pid = p.get("id")
        if not pid:
            continue
        out[pid] = p
        short = pid.split("_", 1)[0]
        out.setdefault(short, p)
    return out


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _query_for_prompt(
    prompt_id: str,
    gold: dict[str, dict],
    prompts: dict[str, dict],
) -> str | None:
    """Resolve the query string a prompt-id corresponds to. Checks gold first
    (gold queries are the same strings sent to the gateway), then falls back
    to prompts.json[id].turns[0].user."""
    entry = gold.get(prompt_id)
    if entry:
        q = entry.get("query")
        if q:
            return q
    prompt = prompts.get(prompt_id)
    if prompt:
        turns = prompt.get("turns") or []
        if turns:
            user = turns[0].get("user")
            if user:
                return user
    return None


def _strip_at_filter(text: str) -> str:
    """Strip a leading ``@filter `` token from a query so we substring-match
    on the substantive part. Matches the convention used by
    ``eval_retrieval_metrics.match_traces_to_prompts``."""
    t = text.strip()
    if t.startswith("@"):
        sp = t.find(" ")
        if sp > 0:
            t = t[sp + 1:]
    return t


def _select_records(
    records: list[dict],
    query_hint: str | None,
) -> tuple[list[dict], dict | None]:
    """Return (all_matching_records, selected_record). If a ``query_hint`` is
    provided, match by substring against ``raw_user_query``. Otherwise return
    every record. The selected record is the most-recent timestamp among
    matches."""
    if not records:
        return [], None

    if query_hint:
        needle = _strip_at_filter(query_hint).lower()[:60].strip()
        candidates = [
            r for r in records
            if needle and needle in (r.get("raw_user_query") or "").lower()
        ]
    else:
        candidates = list(records)

    if not candidates:
        return [], None

    def _ts(r: dict) -> str:
        return r.get("timestamp") or ""

    candidates_sorted = sorted(candidates, key=_ts)
    return candidates, candidates_sorted[-1]


# ---------------------------------------------------------------------------
# Analysis primitives
# ---------------------------------------------------------------------------


def _detect_mode(record: dict) -> str:
    """Heuristic: 'hybrid' when the record carries either lexical or fusion
    candidate lists; 'dense' otherwise. Stage 3.0 only writes dense traces but
    the inspector must already handle the hybrid shape so future runs work."""
    if any(
        k in record
        for k in (
            "candidates_text_lexical_before_fusion",
            "candidates_text_dense_before_fusion",
            "candidates_text_after_fusion",
        )
    ):
        return "hybrid"
    timings = record.get("timings_ms") or {}
    if any(k.startswith("lexical_") or k.startswith("rrf_") for k in timings):
        return "hybrid_legacy"
    return "dense"


def _hybrid_extras(record: dict, chunk_id: Any) -> dict[str, Any]:
    """If hybrid trace shape exists, surface dense_rank / lexical_rank /
    rrf_score / lexical_query_mode for one chunk_id."""
    out: dict[str, Any] = {
        "dense_rank": None,
        "lexical_rank": None,
        "rrf_score": None,
        "lexical_query_mode": None,
    }

    def _rank_in(seq: Iterable[dict]) -> int | None:
        for i, c in enumerate(seq or [], start=1):
            if c.get("chunk_id") == chunk_id:
                return i
        return None

    dense = record.get("candidates_text_dense_before_fusion")
    lexical = record.get("candidates_text_lexical_before_fusion")
    fused = record.get("candidates_text_after_fusion")
    if dense is not None:
        out["dense_rank"] = _rank_in(dense)
    if lexical is not None:
        out["lexical_rank"] = _rank_in(lexical)
    if fused:
        for c in fused:
            if c.get("chunk_id") == chunk_id:
                out["rrf_score"] = c.get("rrf_score")
                break
    out["lexical_query_mode"] = (
        (record.get("retrieval_config") or {}).get("lexical_query_mode")
    )
    return out


def _text_candidates(record: dict) -> list[dict]:
    """Return the canonical text-candidate list, preferring the
    after-fusion list when present so the report tracks what reached
    selection."""
    fused = record.get("candidates_text_after_fusion")
    if fused:
        return fused
    return record.get("candidates_text_before_selection") or []


def _image_candidates(record: dict) -> list[dict]:
    return record.get("candidates_image_before_selection") or []


def _final_context(record: dict) -> list[dict]:
    return record.get("final_context_chunks") or []


def _front_back_counts(cands: list[dict], k: int) -> tuple[int, int]:
    topk = cands[:k]
    fm = sum(1 for c in topk if c.get("front_matter_like"))
    bm = sum(1 for c in topk if c.get("back_matter_like"))
    return fm, bm


def _structural_coverage(cands: list[dict]) -> dict[str, Any]:
    n = len(cands)
    if not n:
        return {
            "n": 0,
            "heading_path_present_pct": 0.0,
            "element_type_present_pct": 0.0,
            "bbox_present_pct": 0.0,
            "page_size_present_pct": 0.0,
            "missing_structural_pct": 0.0,
        }
    hp = sum(1 for c in cands if c.get("heading_path"))
    et = sum(1 for c in cands if c.get("element_type"))
    bb = sum(1 for c in cands if c.get("bbox_present"))
    ps = sum(1 for c in cands if c.get("page_size_present"))
    fully_missing = sum(
        1 for c in cands
        if not c.get("heading_path")
        and not c.get("element_type")
        and not c.get("bbox_present")
        and not c.get("page_size_present")
    )
    return {
        "n": n,
        "heading_path_present_pct": round(100.0 * hp / n, 1),
        "element_type_present_pct": round(100.0 * et / n, 1),
        "bbox_present_pct": round(100.0 * bb / n, 1),
        "page_size_present_pct": round(100.0 * ps / n, 1),
        "missing_structural_pct": round(100.0 * fully_missing / n, 1),
    }


def _gold_analysis(
    gold_ids: list[int],
    text_cands: list[dict],
    image_cands: list[dict],
    final_ctx: list[dict],
) -> dict[str, Any]:
    """Compute per-gold-chunk presence + recall@k + MRR using the same logic
    as eval_retrieval_metrics so numbers are consistent."""
    gold_set = {int(g) for g in gold_ids}
    cands = list(text_cands) + list(image_cands)
    cand_ids = [c.get("chunk_id") for c in cands]
    final_ids = [c.get("chunk_id") for c in final_ctx]

    rank_by_id: dict[Any, int] = {}
    for rank, cid in enumerate(cand_ids, start=1):
        if cid not in rank_by_id:
            rank_by_id[cid] = rank
    final_idx_by_id: dict[Any, int] = {}
    for i, cid in enumerate(final_ids):
        if cid not in final_idx_by_id:
            final_idx_by_id[cid] = i

    cand_by_id = {c.get("chunk_id"): c for c in cands}
    final_by_id = {c.get("chunk_id"): c for c in final_ctx}

    per_gold: list[dict] = []
    first_hit_rank: int | None = None
    for gid in gold_ids:
        gid_int = int(gid)
        rank = rank_by_id.get(gid_int)
        in_final = gid_int in final_idx_by_id
        c = cand_by_id.get(gid_int) or final_by_id.get(gid_int) or {}
        per_gold.append(
            {
                "chunk_id": gid_int,
                "in_candidates": rank is not None,
                "candidate_rank": rank,
                "in_final_context": in_final,
                "final_order": (
                    final_idx_by_id[gid_int] if in_final else None
                ),
                "heading_path": c.get("heading_path"),
                "element_type": c.get("element_type"),
                "front_matter_like": c.get("front_matter_like"),
                "back_matter_like": c.get("back_matter_like"),
                "content_length": c.get("content_length"),
                "caption_length": c.get("caption_length"),
                "meta_embedding_error": c.get("meta_embedding_error"),
            }
        )
        if rank is not None:
            if first_hit_rank is None or rank < first_hit_rank:
                first_hit_rank = rank

    def _recall_at(k: int) -> float:
        if not gold_set:
            return 0.0
        topk = set(cand_ids[:k])
        return round(len(topk & gold_set) / len(gold_set), 3)

    return {
        "n_gold": len(gold_set),
        "first_hit_rank": first_hit_rank,
        "mrr": round(1.0 / first_hit_rank, 3) if first_hit_rank else 0.0,
        "recall@1": _recall_at(1),
        "recall@5": _recall_at(5),
        "recall@10": _recall_at(10),
        "recall@20": _recall_at(20),
        "any_gold_in_final": any(p["in_final_context"] for p in per_gold),
        "per_gold": per_gold,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _md_escape(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def _truncate(s: Any, n: int) -> str:
    text = "" if s is None else str(s)
    return text if len(text) <= n else text[: n - 1] + "…"


def _fmt_flag(value: Any) -> str:
    if value is True:
        return "Y"
    if value is False:
        return "N"
    return "-"


def _fmt_score(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "-"


def _render_md(payload: dict) -> str:
    lines: list[str] = []
    s = payload["summary"]
    lines.append("# Retrieval trace inspection")
    lines.append("")
    lines.append("## Trace summary")
    lines.append("")
    lines.append(f"- **Trace file:** `{s['trace_path']}`")
    lines.append(f"- **Records in file:** {s['record_count']}")
    lines.append(f"- **Records matching filter:** {s['matched_count']}")
    lines.append(f"- **Selected record req_id:** `{s.get('req_id') or '-'}`")
    lines.append(f"- **Selected timestamp:** `{s.get('timestamp') or '-'}`")
    lines.append(f"- **Retrieval mode (heuristic):** `{s['retrieval_mode']}`")
    lines.append(f"- **Selected model:** `{s.get('model_requested') or '-'}`")
    lines.append(f"- **Raw user query:** {_md_escape(s.get('raw_user_query'))}")
    lines.append(
        f"- **Rewritten query:** {_md_escape(s.get('rewritten_query'))}"
    )
    if s.get("filter_prompt_id"):
        lines.append(
            f"- **Filter prompt-id:** `{s['filter_prompt_id']}` "
            f"(query hint: {_md_escape(s.get('filter_query_hint'))})"
        )
    lines.append("")

    if payload.get("warnings"):
        lines.append("### Warnings")
        for w in payload["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    # Top 20 candidates (text)
    lines.append("## Top 20 candidates (text)")
    lines.append("")
    hybrid = s["retrieval_mode"] in ("hybrid", "hybrid_legacy")
    if hybrid:
        lines.append(
            "| rank | chunk_id | page | doc_filename | score | dense_rank | "
            "lexical_rank | rrf_score | lexical_query_mode | heading_path | "
            "element_type | front_matter_like | content_length |"
        )
        lines.append(
            "|---:|---:|---:|---|---:|---:|---:|---:|---|---|---|:---:|---:|"
        )
    else:
        lines.append(
            "| rank | chunk_id | page | doc_filename | score | heading_path "
            "| element_type | front_matter_like | content_length |"
        )
        lines.append(
            "|---:|---:|---:|---|---:|---|---|:---:|---:|"
        )
    for rank, c in enumerate(payload["top_text"], start=1):
        hp = _truncate(c.get("heading_path"), 40)
        et = _truncate(c.get("element_type"), 18)
        fn = _truncate(c.get("filename"), 50)
        page = c.get("page")
        score = _fmt_score(c.get("score"))
        fm = _fmt_flag(c.get("front_matter_like"))
        cl = c.get("content_length")
        cl = "-" if cl is None else cl
        if hybrid:
            extras = c.get("_hybrid", {})
            lines.append(
                f"| {rank} | {c.get('chunk_id', '-')} | {page if page is not None else '-'} | "
                f"{_md_escape(fn)} | {score} | "
                f"{extras.get('dense_rank') or '-'} | "
                f"{extras.get('lexical_rank') or '-'} | "
                f"{_fmt_score(extras.get('rrf_score'))} | "
                f"{_md_escape(extras.get('lexical_query_mode'))} | "
                f"{_md_escape(hp)} | {_md_escape(et)} | {fm} | {cl} |"
            )
        else:
            lines.append(
                f"| {rank} | {c.get('chunk_id', '-')} | {page if page is not None else '-'} | "
                f"{_md_escape(fn)} | {score} | {_md_escape(hp)} | "
                f"{_md_escape(et)} | {fm} | {cl} |"
            )
    if not payload["top_text"]:
        lines.append("_No text candidates in this record._")
    lines.append("")

    # Final context
    lines.append("## Final context")
    lines.append("")
    lines.append(
        "| order | chunk_id | source_label | page | score | heading_path | "
        "element_type | diagnostic_flags |"
    )
    lines.append("|---:|---:|---|---:|---:|---|---|---|")
    for c in payload["final_context"]:
        flags = []
        if c.get("front_matter_like"):
            flags.append("front")
        if c.get("back_matter_like"):
            flags.append("back")
        reasons = c.get("front_or_back_matter_reason") or []
        if reasons:
            flags.append("reasons=" + ",".join(reasons))
        if c.get("meta_embedding_error"):
            flags.append(f"emb_err={c['meta_embedding_error']}")
        flag_str = "; ".join(flags) if flags else "-"
        lines.append(
            f"| {c.get('order_in_context', '-')} | {c.get('chunk_id', '-')} | "
            f"{_md_escape(c.get('source_label'))} | "
            f"{c.get('page') if c.get('page') is not None else '-'} | "
            f"{_fmt_score(c.get('score'))} | "
            f"{_md_escape(_truncate(c.get('heading_path'), 40))} | "
            f"{_md_escape(_truncate(c.get('element_type'), 18))} | "
            f"{_md_escape(flag_str)} |"
        )
    if not payload["final_context"]:
        lines.append("_No final context chunks in this record._")
    lines.append("")

    # Front/back matter analysis
    lines.append("## Front/back matter analysis")
    lines.append("")
    fb = payload["front_back"]
    lines.append(
        "| scope | front_matter_like | back_matter_like |"
    )
    lines.append("|---|---:|---:|")
    lines.append(
        f"| top-6 candidates | {fb['top6'][0]} | {fb['top6'][1]} |"
    )
    lines.append(
        f"| top-10 candidates | {fb['top10'][0]} | {fb['top10'][1]} |"
    )
    lines.append(
        f"| top-20 candidates | {fb['top20'][0]} | {fb['top20'][1]} |"
    )
    lines.append(
        f"| final context | {fb['final'][0]} | {fb['final'][1]} |"
    )
    lines.append("")

    # Gold chunk analysis
    if payload.get("gold"):
        g = payload["gold"]
        lines.append("## Gold chunk analysis")
        lines.append("")
        lines.append(
            f"- **prompt_id:** `{payload['summary']['filter_prompt_id']}`"
        )
        lines.append(f"- **gold_chunk_ids:** {g.get('gold_chunk_ids')}")
        lines.append(f"- **n_gold:** {g['metrics']['n_gold']}")
        lines.append(
            f"- **first_hit_rank:** {g['metrics']['first_hit_rank']}"
        )
        lines.append(f"- **MRR:** {g['metrics']['mrr']:.3f}")
        lines.append(f"- **recall@1:** {g['metrics']['recall@1']:.3f}")
        lines.append(f"- **recall@5:** {g['metrics']['recall@5']:.3f}")
        lines.append(f"- **recall@10:** {g['metrics']['recall@10']:.3f}")
        lines.append(f"- **recall@20:** {g['metrics']['recall@20']:.3f}")
        lines.append(
            f"- **any gold reached final context:** "
            f"{'yes' if g['metrics']['any_gold_in_final'] else 'no'}"
        )
        lines.append("")
        lines.append(
            "| chunk_id | in_candidates | candidate_rank | in_final | "
            "final_order | heading_path | element_type | front_matter_like | "
            "back_matter_like | content_length | embedding_error |"
        )
        lines.append(
            "|---:|:---:|---:|:---:|---:|---|---|:---:|:---:|---:|---|"
        )
        for pg in g["metrics"]["per_gold"]:
            cl = pg.get("content_length")
            if cl is None:
                cl = pg.get("caption_length")
            cl = "-" if cl is None else cl
            lines.append(
                f"| {pg['chunk_id']} | "
                f"{'Y' if pg['in_candidates'] else 'N'} | "
                f"{pg['candidate_rank'] or '-'} | "
                f"{'Y' if pg['in_final_context'] else 'N'} | "
                f"{pg['final_order'] if pg['final_order'] is not None else '-'} | "
                f"{_md_escape(_truncate(pg.get('heading_path'), 40))} | "
                f"{_md_escape(_truncate(pg.get('element_type'), 18))} | "
                f"{_fmt_flag(pg.get('front_matter_like'))} | "
                f"{_fmt_flag(pg.get('back_matter_like'))} | "
                f"{cl} | "
                f"{_md_escape(pg.get('meta_embedding_error'))} |"
            )
        if g.get("excluded_false_positive_chunk_ids"):
            lines.append("")
            lines.append(
                "_Excluded false-positive chunk ids (per gold annotations):_ "
                + ", ".join(
                    str(x) for x in g["excluded_false_positive_chunk_ids"]
                )
            )
        lines.append("")

    # Structural-metadata coverage
    lines.append("## Structural-metadata coverage")
    lines.append("")
    sc = payload["structural_coverage"]
    lines.append(f"- **Candidate count:** {sc['n']}")
    lines.append(f"- **heading_path present:** {sc['heading_path_present_pct']}%")
    lines.append(f"- **element_type present:** {sc['element_type_present_pct']}%")
    lines.append(f"- **bbox present:** {sc['bbox_present_pct']}%")
    lines.append(f"- **page_size present:** {sc['page_size_present_pct']}%")
    lines.append(
        f"- **fully missing structural metadata:** "
        f"{sc['missing_structural_pct']}%"
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--trace",
        required=True,
        help="Path to retrieval.jsonl",
    )
    p.add_argument(
        "--gold",
        default=None,
        help="Optional gold-chunks JSON (e.g. data/eval/gold_chunks.phase0.json)",
    )
    p.add_argument(
        "--prompt-id",
        default=None,
        help="Optional prompt-id (e.g. p04 or p04_bmw_list_completeness)",
    )
    p.add_argument(
        "--prompts-json",
        default=str(DEFAULT_PROMPTS_PATH),
        help="Optional prompts.json path for query lookup",
    )
    p.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for the Markdown/JSON report",
    )
    args = p.parse_args()

    trace_path = Path(args.trace)
    if not trace_path.is_absolute():
        trace_path = ROOT / trace_path
    if not trace_path.exists():
        print(f"ERROR: trace file not found: {trace_path}", file=sys.stderr)
        return 2

    records = _read_jsonl(trace_path)
    gold_map = _load_gold(Path(args.gold)) if args.gold else {}
    prompts_map = _load_prompts(Path(args.prompts_json)) if args.prompts_json else {}

    query_hint: str | None = None
    warnings: list[str] = []
    if args.prompt_id:
        query_hint = _query_for_prompt(args.prompt_id, gold_map, prompts_map)
        if not query_hint:
            warnings.append(
                f"prompt_id `{args.prompt_id}` could not be resolved to a "
                "query via --gold or --prompts-json; falling back to the "
                "latest record in the file"
            )

    matched, selected = _select_records(records, query_hint)
    if not selected:
        if args.prompt_id and query_hint:
            warnings.append(
                f"No trace record matched the query for prompt-id "
                f"`{args.prompt_id}` (substring hint: "
                f"`{(query_hint or '')[:60]}`)"
            )
        if records:
            selected = sorted(records, key=lambda r: r.get("timestamp") or "")[-1]
            matched = records if not args.prompt_id else matched

    if selected is None:
        print(
            "[inspector] no records in trace file — nothing to inspect.",
            file=sys.stderr,
        )
        # Still write a stub report so callers can tell the run completed.

    # Analysis
    text_cands = _text_candidates(selected) if selected else []
    image_cands = _image_candidates(selected) if selected else []
    final_ctx = _final_context(selected) if selected else []
    retrieval_mode = _detect_mode(selected) if selected else "unknown"

    top_text = list(text_cands)[:20]
    if retrieval_mode in ("hybrid", "hybrid_legacy") and selected is not None:
        for c in top_text:
            extras = _hybrid_extras(selected, c.get("chunk_id"))
            c.setdefault("_hybrid", extras)

    fb_counts = {
        "top6": _front_back_counts(text_cands, 6),
        "top10": _front_back_counts(text_cands, 10),
        "top20": _front_back_counts(text_cands, 20),
        "final": (
            sum(1 for c in final_ctx if c.get("front_matter_like")),
            sum(1 for c in final_ctx if c.get("back_matter_like")),
        ),
    }
    structural = _structural_coverage(text_cands)

    gold_payload: dict | None = None
    if args.prompt_id and gold_map and args.prompt_id in gold_map and selected:
        gold_entry = gold_map[args.prompt_id]
        gold_ids = gold_entry.get("gold_chunk_ids") or []
        if gold_ids:
            metrics = _gold_analysis(gold_ids, text_cands, image_cands, final_ctx)
            gold_payload = {
                "gold_chunk_ids": gold_ids,
                "excluded_false_positive_chunk_ids": gold_entry.get(
                    "excluded_false_positive_chunk_ids"
                ),
                "metrics": metrics,
            }
        else:
            warnings.append(
                f"gold entry for `{args.prompt_id}` has empty gold_chunk_ids"
            )
    elif args.prompt_id and not gold_map:
        warnings.append(
            "prompt-id given but no --gold supplied; skipping gold-chunk analysis"
        )

    summary = {
        "trace_path": str(
            trace_path.relative_to(ROOT) if trace_path.is_relative_to(ROOT) else trace_path
        ),
        "record_count": len(records),
        "matched_count": len(matched),
        "filter_prompt_id": args.prompt_id,
        "filter_query_hint": query_hint,
        "retrieval_mode": retrieval_mode,
        "req_id": (selected or {}).get("req_id"),
        "timestamp": (selected or {}).get("timestamp"),
        "model_requested": (selected or {}).get("model_requested"),
        "raw_user_query": (selected or {}).get("raw_user_query"),
        "rewritten_query": (selected or {}).get("rewritten_query"),
    }

    payload = {
        "summary": summary,
        "warnings": warnings,
        "top_text": top_text,
        "final_context": final_ctx,
        "front_back": fb_counts,
        "structural_coverage": structural,
    }
    if gold_payload:
        payload["gold"] = gold_payload

    # Output
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = _now_stamp()
    label = args.prompt_id or "all"
    md_path = out_dir / f"{stamp}_{label}_inspection.md"
    json_path = out_dir / f"{stamp}_{label}_inspection.json"

    md_path.write_text(_render_md(payload), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"[inspector] wrote {md_path}", file=sys.stderr)
    print(f"[inspector] wrote {json_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
