# Phase 0 External Review Report

This report is intended to be pasted to Claude Web / ChatGPT or used as the
handoff note before deciding whether Phase 1 should begin.

## Scope

Phase 0 only: retrieval diagnostics, trace tooling, index-integrity reports,
BMW p04 diagnosis, missing-embedding dry-run tooling, gold-chunk scaffold, eval
trace capture, and retrieval metric scaffold.

Phase 1 was not started. No metadata prefixing, hybrid retrieval, reranking,
backfill execution, prompt changes, generator changes, schema changes, or
embedding-model changes were made.

## What Claude Code Implemented

Claude Code implemented most of the requested Phase 0 tooling:

- Added `RAG_TRACE` / `RAG_TRACE_PATH` handling in `rag-gateway`.
- Added retrieval trace JSONL support and per-stage timing capture.
- Added a diagnostic retrieval path so `diagnose_bmw_p04.py` could call the
  same retrieval function as production without invoking the LLM.
- Added index-integrity reporting:
  - `scripts/report_rag_index_integrity.py`
  - `data/eval/phase0_baseline/index_integrity_report.md`
  - `data/eval/phase0_baseline/index_integrity_report.json`
- Added BMW p04 targeted diagnostic:
  - `scripts/diagnose_bmw_p04.py`
  - `data/eval/phase0_baseline/bmw_p04_diagnostic.md`
  - `data/eval/phase0_baseline/bmw_p04_diagnostic.json`
- Added missing-embedding dry-run/backfill script:
  - `scripts/backfill_missing_embeddings.py`
  - `data/eval/phase0_baseline/embedding_backfill_dryrun.md`
  - `data/eval/phase0_baseline/embedding_backfill_dryrun.json`
- Added gold-chunk scaffold:
  - `data/eval/gold_chunks.template.json`
- Extended eval harness trace capture:
  - `scripts/eval_run.py`
- Added retrieval metric scaffold:
  - `scripts/eval_retrieval_metrics.py`
- Added Phase 1 planning note:
  - `docs/plans/retrieval_phase1_metadata_prefix_plan.md`
- Added Phase 0 summary:
  - `docs/phase0_summary.md`

Claude Code also created a local `.venv-phase0/` to run host-side diagnostic
scripts with `psycopg`.

## Issues Found During Review

The initial implementation was useful but had several issues that needed fixing
before it should be trusted:

- It introduced retrieval behavior drift by adding a cross-source retrieval
  branch that was not part of the original production path. This violated the
  Phase 0 rule that diagnostics must not change retrieval behavior.
- It changed caption/context sanitization in a way that could alter final
  source/image suffix behavior. That was explicitly out of scope.
- The diagnostic endpoint was exposed as a normal route instead of being dead
  when `RAG_TRACE=false`.
- The p04 classification was stated as `low_rank` with high confidence before
  live traced retrieval evidence existed.
- Backfill execution needed stronger safeguards around host-reachable Ollama
  configuration, ingest-compatible `/api/embed` semantics, and non-null
  embedding overwrite protection.
- Eval trace summary fields needed to match the Phase 0 acceptance wording.
- The gold-chunk scaffold needed stable `p01` through `p07` prompt keys.

## Fixes Applied During Review

The review/fix pass corrected those issues:

- Restored the original retrieval shape in `context.py`: one text vector search
  plus one image vector search, followed by the existing merge/sort/context
  assembly behavior.
- Removed unapproved caption/context sanitization changes.
- Registered `/v1/diagnostic/retrieval` only when `RAG_TRACE=true`; after the
  gateway was returned to default mode, the endpoint returned `404`.
- Kept diagnostic endpoint calls from polluting `data/rag-traces/retrieval.jsonl`;
  JSONL traces remain for `/v1/chat/completions` traffic when tracing is on.
- Hardened `scripts/backfill_missing_embeddings.py`:
  - dry-run remains default;
  - `--execute` is required for writes;
  - non-null embeddings require `--force`;
  - host-reachable Ollama URL must be explicit for execution;
  - failures preserve `embedding_error_history`;
  - raw `content_text` is never modified.
- Updated `scripts/eval_run.py` to record:
  - `rag_trace_enabled`
  - `rag_trace_path`
  - `trace_record_count`
- Corrected the p04 status from premature `low_rank` to "unknown until live
  trace", then ran the live trace and updated the interpretation.

## Live Traced p04 Diagnostic

The gateway was rebuilt and temporarily restarted with tracing enabled:

```bash
docker compose build rag-gateway
RAG_TRACE=true docker compose up -d rag-gateway
python3 scripts/diagnose_bmw_p04.py
docker compose up -d rag-gateway
```

Post-run checks confirmed:

- `rag-gateway` was healthy with `RAG_TRACE=true` during the diagnostic.
- The trace mount was writable.
- After reset, `RAG_TRACE=false`.
- After reset, `/v1/diagnostic/retrieval` returned `404`.
- Phase 1 was not started.

The live diagnostic produced a mechanical classification of `generation`
because chunk `36880` reached retrieval candidates and final context:

- chunk: `36880`
- page: `37`
- rank: `6`
- score: `0.6926`
- final context order: `6`

## Evidence-Quality Audit

The live trace alone was not enough because the diagnostic's brand matcher was
loose. It matched chunk `36880`, but full-text inspection showed that chunk
`36880` is a table-of-contents chunk, not answer-bearing evidence for p04.

I added and ran:

```bash
python3 scripts/audit_bmw_p04_evidence_quality.py
```

New outputs:

- `data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.md`
- `data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.json`

The audit labelled all 17 original p04 brand-term matches.

Key findings:

- `36880` reached final context but is `toc_or_index_only`.
- No true answer-bearing original brand-term chunk reached retrieval candidates.
- No true answer-bearing original brand-term chunk reached final context.
- Embedded answer-bearing partial chunks exist:
  - `37032` - MINI / Rolls-Royce section text
  - `37033` - MINI / Rolls-Royce delivery table
  - `37040` - BMW Motorrad market launches/deliveries
  - `37041` - BMW motorcycle deliveries / markets table
  - `37047` - BMW Motorrad new-model discussion
- One answer-bearing partial chunk is invisible to retrieval because embedding
  is NULL:
  - `37039` - BMW Motorrad segment introduction,
    `meta.embedding_error="ollama_embed_failed"`
- BMW overview and segment pages 38-39 contain relevant headings but are noisy
  and partially garbled after extraction.

Expanded matcher terms included:

- `Konzernmarken`
- `Markenportfolio`
- `Marken des BMW Group`
- `BMW Group im Überblick`
- `Organisation und Geschäftsmodell`
- `Segment Automobile`
- `Segment Motorräder`
- `Segment Finanzdienstleistungen`
- `BMW Motorrad`
- `Motorräder`
- `MINI gesamt`
- `Rolls-Royce gesamt`

Expanded matches found more relevant overview/segment chunks, but the only
expanded matches in the traced retrieval/final context were still index-style
chunks: `36880` and `38005`.

## Corrected Classification

Mechanical decision-tree classification:

```text
generation
```

Corrected substantive classification:

```text
mixed_failure
```

Explanation: p04 should not be treated as a pure generation failure. The only
matching chunk that reached final context was a table-of-contents chunk. Real
answer-bearing partial evidence exists but did not rank into retrieval
candidates or final context, and one important BMW Motorrad evidence chunk has
a NULL embedding. The evidence points to a mixed retrieval/evidence-quality
failure plus a missing-embedding component, with extraction noise on BMW
overview pages as a secondary risk.

## Validation Status

Completed successfully:

- `docker compose config --quiet`
- `python3 -m py_compile` for changed Python files
- `python3 scripts/report_rag_index_integrity.py`
- `python3 scripts/backfill_missing_embeddings.py --dry-run`
- `docker compose build rag-gateway`
- `RAG_TRACE=true docker compose up -d rag-gateway`
- `python3 scripts/diagnose_bmw_p04.py`
- `docker compose up -d rag-gateway`
- `python3 scripts/audit_bmw_p04_evidence_quality.py`
- `python3 scripts/eval_retrieval_metrics.py --run data/eval/runs/20260506_015332__gemma4_26b --gold data/eval/gold_chunks.template.json`

The gateway was returned to default `RAG_TRACE=false` after live validation.

## Recommendation

Do not proceed from the mechanical `generation` label.

Recommended next decision after review:

1. If Phase 1 is approved, first run a targeted BMW missing-embedding backfill
   and re-run p04. This tests the cheapest likely contributor without changing
   retrieval architecture.
2. If answer-bearing embedded chunks still do not rank, move to the approved
   retrieval/evidence-quality branch, such as deterministic metadata prefixes
   or another explicitly approved retrieval improvement.
3. Trace p07 before committing to broader retrieval work, because p07 is the
   separate RSS/PDF corpus-skew failure mode.

Do not start hybrid retrieval, reranking, metadata-prefix re-embedding, prompt
rewrites, or backfill execution without explicit approval.
