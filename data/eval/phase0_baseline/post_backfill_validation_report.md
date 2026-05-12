# Phase 0 Post-Backfill Read-Only Validation

- **Captured at:** 2026-05-06T14:25:59+00:00
- **Run dir:** `data/eval/runs/20260506_162128__phase0_post_backfill_p04_p07_gemma4`
- **Phase 0 checkpoint commit:** `76938b9`

## Backfill Outcome

- Target chunks before execution: **486**
- Successful backfills: **12**
- Failed backfills: **474**
- BMW NULL embeddings after: **476**
- BMW NULL + gibberish cleanup error after: **474**
- BMW NULL + no embedding_error after: **2**
- Chunk 37039 embedded: **True**, dim **1024**

## Extraction-Quality Sampling

- Sample labels: `{'genuine_gibberish': 5}`
- Distinct pages with NULL embeddings: **200**
- Interpretation: Failures are clustered on some layout/table-heavy pages but span many pages, indicating a broad BMW extraction/noise issue rather than one isolated page pair.

Top pages by remaining NULL embeddings:

| page | failed chunks |
|---:|---:|
| 143 | 19 |
| 275 | 19 |
| 274 | 17 |
| 48 | 14 |
| 128 | 12 |
| 269 | 12 |
| 139 | 10 |
| 276 | 9 |
| 281 | 9 |
| 73 | 6 |

NULL embeddings with no `embedding_error`:

| chunk | page | type | chars | reason |
|---:|---:|---|---:|---|
| 38082 | 73 | image | 0 | empty `pdf_image` row outside text backfill target |
| 38090 | 115 | image | 0 | empty `pdf_image` row outside text backfill target |

## p04 Post-Backfill Classification

- Mechanical diagnostic classification: `generation`
- Evidence-quality corrected classification: `mixed_failure`
- Final post-backfill classification: **`mixed_failure`**
- Explanation: The live trace's mechanical classification was generation, but the only original brand-term match in final context was chunk 36880, a table-of-contents chunk. True answer-bearing partial evidence exists in chunks 37032, 37033, 37039, 37040, 37041, and 37047, all of which are now embedded, but none of those reached retrieval candidates or final context. The corrected substantive classification is therefore mixed: ranking/evidence-quality failure for p04 plus a broader BMW extraction/noise problem shown by the remaining NULL-embedding cohort.

Gold chunk status:

| chunk | emb | candidate | rank | score | final context | order |
|---:|:---:|:---:|---:|---:|:---:|---:|
| 37032 | Y | N | — | — | N | — |
| 37033 | Y | N | — | — | N | — |
| 37040 | Y | N | — | — | N | — |
| 37041 | Y | N | — | — | N | — |
| 37047 | Y | N | — | — | N | — |
| 37039 | Y | N | — | — | N | — |

Retrieval metrics for p04:

- MRR: **0.000**
- recall@1/@5/@10/@20: **0.00 / 0.00 / 0.00 / 0.00**
- Gold reached final context: **False**

## p07 Trace Classification

- Classification: **`mixed_pdf_rss_context_no_definitive_failure_without_gold`**
- Final context: **2 PDF** chunks, **4 RSS** chunks
- This trace does not show pure RSS dominance: the top two text candidates/final chunks are BMW and Siemens PDF chunks, followed by RSS chunks.
- p07 still lacks gold chunks, so this is a trace classification rather than a scored retrieval metric.

## Gateway Reset

- `RAG_TRACE=false` after reset.
- `/v1/diagnostic/retrieval` returned HTTP 404 after reset.

## Recommended Next Branch

**Primary recommendation:** D: deterministic metadata prefixing for BMW/PDF text chunks

For p04, all six answer-bearing gold chunks are now embedded, but recall@20 and MRR remain 0.0 because none reached candidates/final context. That is ranking/evidence-quality, not generation or context packing. The 474 remaining NULL chunks are a real extraction/noise risk, but they are not the immediate p04 gold-chunk visibility blocker after 37039 was repaired.

**Secondary risk:** BMW extraction/chunking cleanup remains required for the broad 474-chunk gibberish cohort before claiming BMW-wide retrieval quality.

No Phase 1 architectural work was implemented by this validation.
