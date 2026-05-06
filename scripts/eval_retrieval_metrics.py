#!/usr/bin/env python3
"""Phase 0.8 — Retrieval-metric scaffold (no Ragas, no LLM judges).

Reads:
- a populated copy of ``data/eval/gold_chunks.template.json`` (``--gold``)
- retrieval traces from a run directory produced by ``scripts/eval_run.py``
  with ``--rag-trace-path`` capture enabled (``--run``)

Computes, per prompt that has a non-empty ``gold_chunk_ids``:
- recall@1, recall@5, recall@10, recall@20
- mean reciprocal rank (MRR) of the first gold chunk
- whether ANY gold chunk reached the final context

If no gold IDs are populated for any prompt the script exits cleanly with
``status_code=0`` and an informative summary explaining the next step
(populate gold IDs in ``data/eval/gold_chunks.template.json``).

Outputs into the run directory:
    retrieval_metrics.md
    retrieval_metrics.json

TODO (post-Phase 0):
    Once chunk-level recall is locked in as the retrieval baseline, layer
    answer-level metrics on top:
        - Ragas faithfulness / answer-relevancy
        - Ragas context_precision / context_recall (if a question→answer
          ground-truth set is available)
        - LLM-as-judge for synthesized list-completeness on p04, p07
    These belong in a *separate* script (eval_answer_metrics.py) so chunk-
    level metrics remain the source of truth for retrieval quality and are
    not displaced by less-stable LLM-judge scores.

Usage:
    python scripts/eval_retrieval_metrics.py \\
        --run data/eval/runs/<latest_run_dir> \\
        --gold data/eval/gold_chunks.template.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOLD = ROOT / "data" / "eval" / "gold_chunks.template.json"


def load_gold(path: Path) -> dict[str, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        if "gold_chunk_ids" not in value:
            # Skip _about / _failure_modes / etc.
            continue
        out[key] = value
    return out


def load_traces(run_dir: Path) -> list[dict]:
    trace_path = run_dir / "traces" / "retrieval.jsonl"
    if not trace_path.exists():
        return []
    records: list[dict] = []
    with trace_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def match_traces_to_prompts(
    traces: list[dict], prompts: dict[str, dict]
) -> dict[str, dict]:
    """Best-effort mapping from prompt_id → trace record.

    Strategy:
    1. If the trace's ``raw_user_query`` substring-matches the prompt's first
       turn user text (after stripping any leading ``@filter``), we use it.
    2. Otherwise we leave the prompt unmapped.

    This mapping is intentionally conservative — false positives would
    silently corrupt recall@k. When a prompt cannot be uniquely matched the
    metric report flags it.
    """
    out: dict[str, dict] = {}
    for prompt_id, prompt in prompts.items():
        wanted = (prompt.get("query") or "").lower()
        if wanted.startswith("@"):
            sp = wanted.find(" ")
            if sp > 0:
                wanted = wanted[sp + 1:]
        wanted = wanted.strip()
        if not wanted:
            continue
        candidates = [
            t for t in traces
            if wanted[:60] in (t.get("raw_user_query") or "").lower()
        ]
        if len(candidates) == 1:
            out[prompt_id] = candidates[0]
    return out


def compute_metrics(
    gold_ids: list[int], trace: dict
) -> dict:
    text_cands = trace.get("candidates_text_before_selection") or []
    image_cands = trace.get("candidates_image_before_selection") or []
    cands = list(text_cands) + list(image_cands)
    final_ctx = trace.get("final_context_chunks") or []
    gold_set = {int(g) for g in gold_ids}
    cand_chunk_ids = [c.get("chunk_id") for c in cands]

    # First-rank position of any gold chunk among candidates (ordered as the
    # gateway returned them, then by score; we already preserve that order).
    first_hit_rank: int | None = None
    for rank, cid in enumerate(cand_chunk_ids, start=1):
        if cid in gold_set:
            first_hit_rank = rank
            break

    def recall_at(k: int) -> float:
        if not gold_set:
            return 0.0
        topk = set(cand_chunk_ids[:k])
        return len(topk & gold_set) / len(gold_set)

    final_ctx_ids = {c.get("chunk_id") for c in final_ctx}
    return {
        "n_gold": len(gold_set),
        "n_candidates": len(cand_chunk_ids),
        "n_final_context": len(final_ctx),
        "first_hit_rank": first_hit_rank,
        "mrr": (1.0 / first_hit_rank) if first_hit_rank else 0.0,
        "recall@1": recall_at(1),
        "recall@5": recall_at(5),
        "recall@10": recall_at(10),
        "recall@20": recall_at(20),
        "gold_chunk_reached_final_context": bool(gold_set & final_ctx_ids),
    }


def render_md(payload: dict) -> str:
    lines: list[str] = []
    lines.append("# Phase 0.8 — Retrieval-metric scaffold")
    lines.append("")
    lines.append(f"- **Run dir:** `{payload['run_dir']}`")
    lines.append(f"- **Gold file:** `{payload['gold_path']}`")
    lines.append(f"- **Prompts inspected:** {payload['prompts_total']}")
    lines.append(
        f"- **Prompts with gold IDs:** {payload['prompts_with_gold']}"
    )
    lines.append(
        f"- **Prompts mapped to a trace record:** {payload['prompts_mapped']}"
    )
    lines.append("")

    if not payload["per_prompt"]:
        lines.append(
            "_No prompts had populated `gold_chunk_ids`. Populate the gold "
            "scaffold and re-run; this script intentionally exits without "
            "computing meaningless zeros when no ground truth is available._"
        )
        lines.append("")
        return "\n".join(lines)

    lines.append("## Per-prompt metrics")
    lines.append("")
    lines.append(
        "| prompt_id | gold | cands | final | rank₁ | MRR | r@1 | r@5 | "
        "r@10 | r@20 | reached_final |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|"
    )
    for pid, m in payload["per_prompt"].items():
        if m.get("status") == "no_gold":
            continue
        if m.get("status") == "unmapped":
            lines.append(
                f"| {pid} | {len(m.get('gold_ids') or [])} | — | — | — | — | "
                "— | — | — | — | (no trace match) |"
            )
            continue
        metrics = m["metrics"]
        rank = (
            f"{metrics['first_hit_rank']}"
            if metrics["first_hit_rank"] is not None
            else "—"
        )
        lines.append(
            "| {pid} | {ng} | {nc} | {nf} | {rk} | {mrr:.3f} | {r1:.2f} | "
            "{r5:.2f} | {r10:.2f} | {r20:.2f} | {rf} |".format(
                pid=pid,
                ng=metrics["n_gold"],
                nc=metrics["n_candidates"],
                nf=metrics["n_final_context"],
                rk=rank,
                mrr=metrics["mrr"],
                r1=metrics["recall@1"],
                r5=metrics["recall@5"],
                r10=metrics["recall@10"],
                r20=metrics["recall@20"],
                rf="Y" if metrics["gold_chunk_reached_final_context"] else "N",
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", required=True, help="Run directory under data/eval/runs/")
    p.add_argument("--gold", default=str(DEFAULT_GOLD))
    args = p.parse_args()

    run_dir = Path(args.run)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    if not run_dir.exists():
        print(f"ERROR: run dir does not exist: {run_dir}", file=sys.stderr)
        return 2

    gold_path = Path(args.gold)
    if not gold_path.is_absolute():
        gold_path = ROOT / gold_path
    if not gold_path.exists():
        print(f"ERROR: gold file does not exist: {gold_path}", file=sys.stderr)
        return 2

    prompts = load_gold(gold_path)
    traces = load_traces(run_dir)
    mapped = match_traces_to_prompts(traces, prompts)

    per_prompt: dict[str, dict] = {}
    prompts_with_gold = 0
    for pid, prompt in prompts.items():
        gold_ids = prompt.get("gold_chunk_ids") or []
        if not gold_ids:
            per_prompt[pid] = {"status": "no_gold", "gold_ids": []}
            continue
        prompts_with_gold += 1
        trace = mapped.get(pid)
        if not trace:
            per_prompt[pid] = {
                "status": "unmapped",
                "gold_ids": gold_ids,
                "reason": "no trace record matched this prompt's query",
            }
            continue
        per_prompt[pid] = {
            "status": "computed",
            "gold_ids": gold_ids,
            "trace_req_id": trace.get("req_id"),
            "metrics": compute_metrics(gold_ids, trace),
        }

    payload = {
        "run_dir": str(run_dir.relative_to(ROOT)) if run_dir.is_relative_to(ROOT) else str(run_dir),
        "gold_path": str(gold_path.relative_to(ROOT)) if gold_path.is_relative_to(ROOT) else str(gold_path),
        "prompts_total": len(prompts),
        "prompts_with_gold": prompts_with_gold,
        "prompts_mapped": sum(
            1 for v in per_prompt.values() if v.get("status") == "computed"
        ),
        "per_prompt": per_prompt,
    }

    out_md = run_dir / "retrieval_metrics.md"
    out_json = run_dir / "retrieval_metrics.json"
    out_md.write_text(render_md(payload), encoding="utf-8")
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    if prompts_with_gold == 0:
        print(
            "[metrics] no prompts had gold_chunk_ids populated; nothing to "
            "score. Populate data/eval/gold_chunks.template.json (or a copy) "
            "with confirmed gold chunks, then re-run.",
            file=sys.stderr,
        )
        return 0

    print(f"[metrics] wrote {out_md.relative_to(ROOT)}", file=sys.stderr)
    print(f"[metrics] wrote {out_json.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
