# Phase 1.0 Preliminary Report

Status: preliminary evidence work only. No retrieval behavior, schema,
prompting, model, or architecture changes were made. No embedding backfill was
executed.

## Step 0 — Phase 0 Checkpoint State

`git status --short` shows a dirty worktree with Phase 0 files plus unrelated
pre-existing demo/control-center changes. No commit was created because commits
are state-changing and require explicit approval.

Phase 0 files present include:

- retrieval trace tooling: `services/rag-gateway/app/trace.py`,
  `services/rag-gateway/app/context.py`, `services/rag-gateway/app/main.py`
- index-integrity report: `scripts/report_rag_index_integrity.py`
- p04 diagnostic: `scripts/diagnose_bmw_p04.py`
- p04 evidence-quality audit:
  `scripts/audit_bmw_p04_evidence_quality.py`
- missing-embedding dry-run/backfill script:
  `scripts/backfill_missing_embeddings.py`
- gold-chunk scaffold: `data/eval/gold_chunks.template.json`
- phase0 populated gold copy: `data/eval/gold_chunks.phase0.json`
- retrieval metric scaffold: `scripts/eval_retrieval_metrics.py`
- Phase 0 summary and external review report:
  `docs/phase0_summary.md`,
  `docs/phase0_external_review_report.md`

## Step 1 — p04 Gold Evidence

Created:

```text
data/eval/gold_chunks.phase0.json
```

Only p04 was populated. p01-p03 and p05-p07 remain empty because no audit has
identified confident gold chunks for them.

p04 partial gold chunks:

```text
37032
37033
37040
37041
37047
37039
```

Notes:

- p04 is a list-completeness query.
- No single chunk is a perfect full answer.
- These chunks are partial-gold evidence from the p04 evidence-quality audit.
- `37039` is answer-bearing BMW Motorrad evidence but had a NULL embedding
  before targeted backfill.
- `36880` is explicitly excluded because it is table-of-contents/index-only.

Validation:

```bash
python3 -m json.tool data/eval/gold_chunks.phase0.json
```

Result: OK.

## Step 1b — Retrieval Metrics Against Historical Run

Command:

```bash
python3 scripts/eval_retrieval_metrics.py \
  --run data/eval/runs/20260506_015332__gemma4_26b \
  --gold data/eval/gold_chunks.phase0.json
```

Output:

- `data/eval/runs/20260506_015332__gemma4_26b/retrieval_metrics.md`
- `data/eval/runs/20260506_015332__gemma4_26b/retrieval_metrics.json`

Result:

- prompts with gold IDs: 1
- p04 gold IDs: 6
- prompts mapped to trace records: 0
- p04 status: `unmapped`

Limitation: the historical eval run did not contain a trace record matching the
p04 query, so chunk-level recall/MRR could not be computed from that run.

## Step 2 — BMW Targeted Backfill Dry-Run

Command:

```bash
python3 scripts/backfill_missing_embeddings.py --dry-run \
  --doc-filter BMWGroup_Bericht2023.pdf \
  --only-error ollama_embed_failed
```

Result:

- mode: dry-run
- selected chunks: 486
- filenames selected: `BMWGroup_Bericht2023.pdf` only
- embedding error selected: `ollama_embed_failed` only
- chunks with `len(content_text) > 8000`: 0
- chunks with `len(content_text) < 50`: 135
- writes: none
- chunk `37039`: selected

Output:

- `data/eval/phase0_baseline/embedding_backfill_dryrun.md`
- `data/eval/phase0_baseline/embedding_backfill_dryrun.json`

## Step 3 — Backfill Execution Gate

Backfill execution was not run.

Reason:

- Project `.env` has `OLLAMA_BASE_URL=http://ollama:11434`, which is only
  container-internal from the host perspective.
- The project Compose file does not expose the `ollama` service on a project
  host port.
- `http://127.0.0.1:11434` responds on the host, but it is not exposed by this
  project Compose file and its model list does not include `bge-m3`.
- Using that host service for database mutation would not be project-safe.

Read-only check:

```text
model_count=14
has_bge_m3=False
bge_matches=[]
```

Required before `--execute`:

- an explicitly approved project-safe, host-reachable Ollama URL that serves
  `bge-m3`, or
- an explicitly approved alternate execution method that still preserves the
  project safety constraints.

## Current Classification

Pre-backfill p04 remains:

```text
mixed_failure
```

Evidence:

- `36880` reached final context but is table-of-contents/index-only.
- True answer-bearing partial chunks exist.
- Embedded answer-bearing chunks did not reach candidates or final context.
- `37039` is answer-bearing but currently NULL-embedding.

## Recommended Next Gate

Ask for explicit approval before either:

1. committing the Phase 0 / Phase 1.0 checkpoint, or
2. executing targeted BMW backfill with a project-safe Ollama endpoint.

Do not start metadata prefixing, hybrid retrieval, reranking, prompt rewrites,
or p07 architecture work until the BMW backfill execution gate is resolved and
the post-backfill p04 diagnostic has been run.
