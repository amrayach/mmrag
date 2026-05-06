# Phase 0 - Retrieval diagnostics summary

**Status:** Phase 0 diagnostic tooling is implemented and the live traced p04
diagnostic has been run. **Phase 1 has not been started.**

This summary supersedes the earlier draft that classified p04 as `low_rank`
without a live production retrieval trace. That classification was not
supported by the generated diagnostic report.

## Files changed

### Modified

- `services/rag-gateway/app/main.py` - wires optional retrieval tracing into
  `/v1/chat/completions`; registers `/v1/diagnostic/retrieval` only when
  `RAG_TRACE=true`.
- `services/rag-gateway/app/context.py` - adds trace/timing plumbing and
  candidate/final-context snapshots. The retrieval algorithm remains the
  original single text search plus single image search.
- `docker-compose.yml` - adds `RAG_TRACE`, `RAG_TRACE_PATH`, and a local
  `./data/rag-traces:/data/rag-traces` mount for trace capture. No port changes.
- `.gitignore` - ignores `.venv-phase0/` and trace JSONL files while keeping
  `data/rag-traces/.gitkeep`.
- `scripts/eval_run.py` - captures appended RAG trace records into an eval run
  directory and records trace metadata in `summary.json`.

### Added

- `services/rag-gateway/app/trace.py`
- `scripts/_phase0_utils.py`
- `scripts/report_rag_index_integrity.py`
- `scripts/diagnose_bmw_p04.py`
- `scripts/audit_bmw_p04_evidence_quality.py`
- `scripts/backfill_missing_embeddings.py`
- `scripts/eval_retrieval_metrics.py`
- `data/eval/gold_chunks.template.json`
- `data/rag-traces/.gitkeep`
- `docs/plans/retrieval_phase1_metadata_prefix_plan.md`
- `docs/phase0_summary.md`
- `docs/phase0_external_review_report.md`

## New environment variables

| Name | Default | Effect |
|---|---|---|
| `RAG_TRACE` | `false` | When `true`, `/v1/chat/completions` appends one retrieval trace record per request and the diagnostic retrieval endpoint is registered. |
| `RAG_TRACE_PATH` | `/data/rag-traces/retrieval.jsonl` | In-container JSONL trace path, mounted host-side at `data/rag-traces/retrieval.jsonl`. |

## New scripts

- `scripts/report_rag_index_integrity.py`
- `scripts/diagnose_bmw_p04.py`
- `scripts/audit_bmw_p04_evidence_quality.py`
- `scripts/backfill_missing_embeddings.py`
- `scripts/eval_retrieval_metrics.py`

## Generated reports

- `data/eval/phase0_baseline/baseline_state.md`
- `data/eval/phase0_baseline/baseline_state.json`
- `data/eval/phase0_baseline/index_integrity_report.md`
- `data/eval/phase0_baseline/index_integrity_report.json`
- `data/eval/phase0_baseline/bmw_p04_diagnostic.md`
- `data/eval/phase0_baseline/bmw_p04_diagnostic.json`
- `data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.md`
- `data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.json`
- `data/eval/phase0_baseline/embedding_backfill_dryrun.md`
- `data/eval/phase0_baseline/embedding_backfill_dryrun.json`
- `data/eval/gold_chunks.template.json`
- `docs/plans/retrieval_phase1_metadata_prefix_plan.md`
- `docs/phase0_external_review_report.md`

## Reproduction commands

These commands are read-only or dry-run, except where explicitly noted.

```bash
docker compose config --quiet

python3 -m py_compile \
  services/rag-gateway/app/trace.py \
  services/rag-gateway/app/context.py \
  services/rag-gateway/app/main.py \
  scripts/_phase0_utils.py \
  scripts/report_rag_index_integrity.py \
  scripts/diagnose_bmw_p04.py \
  scripts/audit_bmw_p04_evidence_quality.py \
  scripts/backfill_missing_embeddings.py \
  scripts/eval_retrieval_metrics.py \
  scripts/eval_run.py

python3 scripts/report_rag_index_integrity.py
python3 scripts/backfill_missing_embeddings.py --dry-run
python3 scripts/diagnose_bmw_p04.py
python3 scripts/audit_bmw_p04_evidence_quality.py

python3 scripts/eval_retrieval_metrics.py \
  --run data/eval/runs/20260506_015332__gemma4_26b \
  --gold data/eval/gold_chunks.template.json
```

Full p04 retrieval cross-reference was run with a traced rag-gateway:

```bash
docker compose build rag-gateway
RAG_TRACE=true docker compose up -d rag-gateway
python3 scripts/diagnose_bmw_p04.py
docker compose up -d rag-gateway
```

After the diagnostic, `rag-gateway` was restarted back to default
`RAG_TRACE=false`. The diagnostic endpoint returned `404` in default mode,
confirming it is registered only when tracing is enabled.

Eval trace capture, after a traced gateway is running:

```bash
python3 scripts/eval_run.py --label phase0_trace_capture
```

Missing-embedding execution is intentionally manual only:

```bash
python3 scripts/backfill_missing_embeddings.py --execute \
  --doc-filter BMWGroup_Bericht2023.pdf \
  --only-error ollama_embed_failed \
  --ollama-host <host-reachable-ollama-url>
```

## Compose and database

- Compose project name detected: `ammer-mmragv2`.
- Postgres connection method for diagnostic scripts: TCP
  `host=127.0.0.1 port=56154 dbname=rag user=rag_user`.
- No Unix socket / peer-auth path is used by the new diagnostic scripts.

## What was intentionally not changed

- retrieval algorithm
- embedding model
- database schema / DDL
- generator model
- SSE streaming behavior
- final source/image suffix behavior
- existing port bindings
- Tailscale Serve/Funnel configuration

## Phase 1 root-cause classification

**Mechanical live-trace classification:** `generation`.

**Corrected evidence-quality classification:** `mixed_failure`.

The live traced p04 diagnostic found 17 BMW brand-list matching chunks in
`BMWGroup_Bericht2023.pdf`; 16 have embeddings and one chunk (`37039`, page 71)
has `meta.embedding_error="ollama_embed_failed"`. One embedded brand-term match,
`36880` on page 37, appeared in `candidates_text_before_selection` at rank 6
with score `0.6926` and reached `final_context_chunks` at order 6. That is why
the mechanical decision tree produced `generation`.

The follow-up evidence-quality audit corrected the interpretation: chunk
`36880` is a table-of-contents chunk, not answer-bearing evidence for p04. True
answer-bearing partial evidence exists in embedded chunks `37032`, `37033`,
`37040`, `37041`, and `37047`, but none of those reached retrieval candidates or
final context. Chunk `37039` is also answer-bearing for BMW Motorrad but has a
NULL embedding. Therefore p04 should not be treated as a pure generation
failure. The substantive root cause is mixed: ranking/evidence-quality failure
plus a missing-embedding component, with extraction noise on the BMW overview
pages as a secondary risk.

## Evidence required before Phase 1

- Review `data/eval/phase0_baseline/bmw_p04_diagnostic.md` with the final
  traced classification.
- Review `data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.md`; this
  is the corrected interpretation of the traced p04 evidence.
- Review `data/eval/phase0_baseline/index_integrity_report.md`.
- Review `data/eval/phase0_baseline/embedding_backfill_dryrun.md`; do not run
  `--execute` until explicitly approved.
- Decide whether Phase 1 should first run the targeted BMW missing-embedding
  backfill and re-test p04, or proceed directly to an approved retrieval /
  evidence-quality branch.

## Validation status

| Command | Status |
|---|---|
| `docker compose config --quiet` | OK |
| `python3 -m py_compile ...` | OK |
| `python3 scripts/report_rag_index_integrity.py` | OK; wrote index report |
| `python3 scripts/backfill_missing_embeddings.py --dry-run` | OK; selected 486 chunks, wrote dry-run report |
| `docker compose build rag-gateway` | OK; rebuilt traced gateway image |
| `RAG_TRACE=true docker compose up -d rag-gateway` | OK; traced gateway healthy |
| `python3 scripts/diagnose_bmw_p04.py` | OK; classification `generation`; chunk `36880` rank 6 / score `0.6926` reached final context |
| `python3 scripts/audit_bmw_p04_evidence_quality.py` | OK; corrected substantive classification `mixed_failure`; chunk `36880` is TOC-only; no answer-bearing match reached final context |
| `docker compose up -d rag-gateway` | OK; restored default `RAG_TRACE=false`; diagnostic endpoint check returned `404` |
| `python3 scripts/eval_retrieval_metrics.py --run data/eval/runs/20260506_015332__gemma4_26b --gold data/eval/gold_chunks.template.json` | OK; exited cleanly because no gold chunk IDs are populated |

## Stop condition

Stop after Phase 0. Do not implement Phase 1, hybrid retrieval, BM25/tsvector,
GIN indexes, RRF, reranking, contextual retrieval, Ragas metrics, ColPali,
GraphRAG, agentic retrieval, route-based slot allocation, embedding model
changes, or generator model changes without explicit approval.
