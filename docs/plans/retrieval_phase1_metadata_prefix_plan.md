# Phase 1 — Retrieval upgrades, branch-gated on Phase 0.4 classification

**Status:** PLANNING ONLY. Do not implement yet. Implementation is gated on
the Phase 0.4 (`scripts/diagnose_bmw_p04.py`) failure-mode classification
and explicit user approval to proceed.

## Inputs from Phase 0

Phase 0 produced this evidence pack under `data/eval/phase0_baseline/`:

- `baseline_state.{md,json}` — git HEAD, env, reference run pointer
- `index_integrity_report.{md,json}` — corpus state including 493 NULL
  embeddings (488 of them in `BMWGroup_Bericht2023.pdf`), 1,554 PDF text
  chunks total, 10.4% of all chunks carry `meta.heading_path`
- `bmw_p04_diagnostic.{md,json}` — 17 brand-list-related chunks across 13
  pages; 16 embedded, 1 with `meta.embedding_error=ollama_embed_failed`
- `embedding_backfill_dryrun.{md}` — 486 BMW chunks listed for backfill,
  none over 8000 chars (length is not the embed-failure cause)
- `gold_chunks.template.json` — scaffolds for p01..p07 (gold IDs empty)

The classification produced by `scripts/diagnose_bmw_p04.py` selects which
Phase 1 branch executes next. Each branch is described below with its
rollback plan and validation plan.

## Branch A — `missing_chunk`

**Trigger:** the brand-list page is not in `rag_chunks` at all.

**Cause hypothesis:** OpenDataLoader's reading-order pass dropped the
brand-list paragraphs, or layout-aware chunking split the brand list across
chunks that no longer match list-completeness queries.

**Tactical fix (single-doc, scoped):**
1. Reproduce the missing pages locally with `services/pdf-ingest/app/extractor.py`
   in isolation, with `--debug` style logging if needed.
2. Investigate `extractor.py` parameters that might explain the gap:
   - `xycut` reading-order (may split brand-list pages with multi-column layout)
   - `MIN_IMAGE_WIDTH` / `MIN_IMAGE_HEIGHT` / `MIN_IMAGE_BYTES` — irrelevant
     here for text but verify nothing else changed
   - `CHUNK_CHARS` (currently 1500) and `CHUNK_OVERLAP_CHARS` (200) — lower
     values may help when the brand list is dense
3. Re-extract only the affected `doc_id` (`BMWGroup_Bericht2023.pdf`):
   `DELETE FROM rag_chunks WHERE doc_id = ?` then re-run pdf-ingest for
   that single file.

**Out of scope:** corpus-wide re-extraction.

**Rollback:** before delete, snapshot the doc's chunks:
```sql
COPY (SELECT * FROM rag_chunks WHERE doc_id = ?) TO '/tmp/bmw_chunks.csv' CSV HEADER;
```
Restore via `\copy rag_chunks FROM ...`.

**Validation:** re-run `scripts/diagnose_bmw_p04.py`; expect at least one
new chunk that contains the brand list, embedded, with `meta.heading_path`
populated.

## Branch B — `missing_embedding`

**Trigger:** brand-list chunk(s) exist but `embedding IS NULL`.

**Tactical fix:** run the existing dry-run-validated backfill:
```bash
python scripts/backfill_missing_embeddings.py \
    --execute --doc-filter BMWGroup_Bericht2023.pdf \
    --only-error ollama_embed_failed
```

The `--execute` flag re-embeds via the same Ollama bge-m3 endpoint used by
ingestion, writes the resulting embedding to `rag_chunks.embedding`, and
removes `meta.embedding_error` on success. On failure it preserves the
prior error in `meta.embedding_error_history`.

**Out of scope:** changing the embedding model or re-embedding all chunks.

**Rollback:** the backfill never deletes; to revert, set
`embedding = NULL` for the affected chunk_ids and restore
`meta.embedding_error` from `meta.embedding_error_history`. The dry-run
JSON output records the exact chunk_id list.

**Validation:** re-run `scripts/report_rag_index_integrity.py` —
`chunks_null_embedding_total` should drop by the count of successfully
re-embedded chunks. Re-run `scripts/diagnose_bmw_p04.py` — the previously
NULL chunk should now appear in candidates.

## Branch C — `low_rank` ⭐ headline path

**Trigger:** brand-list chunks exist, are embedded, but never reach the
production retrieval candidates (top-k by cosine score).

**Hypothesis:** dense retrieval ranks PDF prose chunks below RSS prose
because RSS articles are short, recent, and topically homogeneous; the
embedding doesn't pick up the structural signal that "this paragraph is the
brand-list section under the 'Konzern' heading on page 71". Phase 1 makes
the structural signal explicit by prefixing the embedding input with a
deterministic metadata header.

### Implementation pattern (no schema migration)

For PDF text chunks only:

```
meta.index_prefix = "<doc_title> › <heading_path joined with ›> › p<page> › <element_type>"
```

Example for chunk 37032 on page 69:
```
"BMW Group Bericht 2023 › Konzernabschluss › Marken › p69 › section"
```

The embedding input becomes:
```
meta.index_prefix + "\n\n" + content_text
```

`content_text` is **never overwritten**. The prefix is stored in the JSONB
`meta` column for transparency and reproducibility.

To detect when an existing embedding needs refreshing, also store:
```
meta.indexed_text_hash = sha256(meta.index_prefix + "\n\n" + content_text)
```

A re-embed pass simply skips chunks whose `meta.indexed_text_hash` matches
the prefix+text it would generate now.

### Scope

- Only PDF text chunks: `meta.source = 'pdf_text'` (or whatever the live
  rss/pdf split shows from Phase 0.3 — verify against
  `index_integrity_report.json: chunks_by_meta_source`).
- Estimated rows to re-embed: **~1,554** (PDF text chunks) — verify against
  `index_integrity_report.json: chunks_by_meta_source.pdf_text`.
- RSS chunks unchanged.
- Image chunks unchanged.
- Schema unchanged: prefix lives in `meta` JSONB.

### Knobs

- Prefix template (start with the canonical form above; do not customize per
  doc-type until p04 is fixed).
- Whether to include `element_type` in the prefix when it equals `section`
  (probably skip for noise reduction).
- Whether to weight prefix tokens by repeating them (start: do NOT).

### Rollback

`UPDATE rag_chunks SET meta = meta - 'index_prefix' - 'indexed_text_hash'`
removes the prefix metadata. Re-running the embed step (without the prefix
codepath) restores the pre-Phase-1 behavior.

### Validation

1. Re-run `scripts/diagnose_bmw_p04.py` — at least one brand-list chunk
   should now appear in `candidates_text_before_selection` with a non-zero
   rank.
2. Re-run `scripts/eval_retrieval_metrics.py --run <new_run> --gold ...`
   with populated gold IDs — `recall@10` for p04 should improve materially.
3. No regression on p01, p02, p03: their per-prompt metrics should hold
   within ±1 rank.
4. Compare TTFT / total latency against the Phase 0.0 reference run
   (`20260506_015332__gemma4_26b`); the +metadata-prefix path adds
   embedding-side cost only (re-embed at ingest, no per-query cost).

## Branch D — `context_packing`

**Trigger:** brand-list chunk(s) reach retrieval candidates but are dropped
during merge/sort/fusion or the image guard.

**Tactical knobs (each tunable separately, NOT bundled):**
1. **Top-k slot allocation** — currently 6 text + 2 image (or 4+4 for
   image-intent queries). For list-completeness, raise text slots to 10–12
   for `@<doc>` queries.
2. **Image guard** — `image_score_min` (0.45 / 0.55) and `max_images`
   (3 / 2). Tune only if image candidates are mistakenly outranking text.
3. **+0.10 image score boost when `doc_filter` is set** — this is the
   `score_boost_applied` field in the trace. Re-evaluate whether boosting
   images squeezes text out of the final context.
4. **Cross-doc-id guard** — non-image queries currently only show images
   from docs with text hits. Confirm this isn't masking the brand-list
   pages indirectly.

Each knob should be flag-gated initially.

**Rollback:** revert the env var(s) or config flags.

**Validation:** same as Branch C: rerun diagnostic, retrieval metrics, and
compare against the Phase 0.0 reference run.

## Branch E — `generation`

**Trigger:** brand-list chunk(s) reach final context but the answer is
still incomplete.

**Out of scope for retrieval upgrades.** This is a prompt or generator
concern. Investigation lives elsewhere:
- prompt template in `services/rag-gateway/app/context.py:SYSTEM_PROMPT`
- model output truncation (`max_tokens=800` in compose)
- model-specific list-completion behavior

**Validation:** generation-side metrics (Ragas faithfulness / completeness)
which are explicitly TODO for a future phase, not Phase 1.

## What Phase 1 will NEVER touch

- the OpenAI-compatible API contract on rag-gateway
- the SSE streaming behavior
- the final source/image suffix shape
- the generator model
- the embedding model identity (only the *input text* changes for Branch C)
- the schema (no DDL — `meta.index_prefix` lives in JSONB)
- port bindings, Tailscale rules, or anything outside this project root

## Recommended order if classification is `low_rank`

1. Land the Phase 1 design doc as a separate PR (this doc).
2. Implement metadata-prefix code path behind `RAG_INDEX_PREFIX=false`
   default-off flag in `services/pdf-ingest/app/extractor.py` (write
   `meta.index_prefix` and `meta.indexed_text_hash`) and in the embed call
   path that consumes them.
3. Re-embed PDF text chunks for one document first (BMWGroup), validate
   p04, then re-embed the rest.
4. Flip `RAG_INDEX_PREFIX=true` only after all three of:
   - p04 recall@10 improves on the populated gold set
   - p01/p02/p03 metrics hold within ±1 rank
   - p07 metrics do not regress (RSS-vs-PDF balance)

Hybrid retrieval, RRF, BM25 / German `tsvector`, `bge-reranker-v2-m3`,
ColPali, GraphRAG, agentic retrieval, and route-based slot allocation are
all explicitly out of scope for Phase 1. They live in Phase 2+, gated on
Phase 1 results.
