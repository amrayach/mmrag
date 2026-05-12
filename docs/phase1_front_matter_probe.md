# Phase 1 Front-Matter Penalty Probe

Captured: 2026-05-07

## Goal

Test whether a simple front-matter / TOC penalty would have been enough to
surface the six p04 BMW answer-bearing gold chunks into fused top-6.

This was a read-only file analysis over the saved Stage 2B V6 hybrid trace. No
gateway rerun, DB query, Docker state change, code change, or commit was made.

## Input Trace

Trace source:

`data/eval/runs/20260507_185509__phase1_hybrid_validation_p04_p07/traces/retrieval.jsonl`

Selected record:

`@BMWGroup Liste alle Marken, Geschäftsbereiche oder Beteiligungen auf, die im BMW Group Bericht 2023 erwähnt werden. Bitte vollständige Liste, nicht nach 3 Punkten aufhören.`

The saved p04 trace contains:

- dense candidates before fusion: 200
- lexical candidates before fusion: 237
- captured fused candidates: top 40
- `RRF_K=60`
- lexical query mode: `or_fallback`

For ranks below top 40, the full fused list was reconstructed from
`candidates_text_dense_before_fusion` and
`candidates_text_lexical_before_fusion` using the same RRF formula:

`rrf_score = sum(1 / (60 + rank))`

Candidate pool size after union: 270.

## Scenarios

- **Original**: no penalty.
- **S1 - TOC/copyright pages only**: chunks on pages `<=10` get
  `rrf_score * 0.5`.
- **S2 - TOC + back-matter**: chunks on pages `<=10` or `>=320` get
  `rrf_score * 0.5`.
- **S3 - heading_path-aware**: not evaluable from the saved trace. The trace
  records candidate page, filename, dense rank, lexical rank, and preview, but
  not `meta.heading_path`. Per read-only constraints, no DB lookup was run to
  recover missing metadata.

## Original Top 10

| rank | chunk | page | score |
|---:|---:|---:|---:|
| 1 | 38005 | 325 | 0.032002 |
| 2 | 38003 | 324 | 0.030092 |
| 3 | 36755 | 1 | 0.029911 |
| 4 | 36756 | 2 | 0.029010 |
| 5 | 36761 | 4 | 0.028589 |
| 6 | 36774 | 8 | 0.028043 |
| 7 | 36880 | 37 | 0.027056 |
| 8 | 37999 | 322 | 0.026779 |
| 9 | 38002 | 323 | 0.026230 |
| 10 | 37998 | 321 | 0.026151 |

Gold chunk ranks:

| chunk | page | original rank | score |
|---:|---:|---:|---:|
| 37047 | 71 | 22 | 0.023385 |
| 37040 | 71 | 31 | 0.021440 |
| 37041 | 71 | 32 | 0.021420 |
| 37039 | 71 | 104 | 0.012049 |
| 37032 | 69 | 140 | 0.009733 |
| 37033 | 69 | 152 | 0.009010 |

Gold chunks in top-6: 0.

## S1 Top 10: Pages <=10 Penalized

| rank | chunk | page | penalized score |
|---:|---:|---:|---:|
| 1 | 38005 | 325 | 0.032002 |
| 2 | 38003 | 324 | 0.030092 |
| 3 | 36880 | 37 | 0.027056 |
| 4 | 37999 | 322 | 0.026779 |
| 5 | 38002 | 323 | 0.026230 |
| 6 | 37998 | 321 | 0.026151 |
| 7 | 37444 | 155 | 0.026070 |
| 8 | 36983 | 56 | 0.025833 |
| 9 | 36986 | 57 | 0.025320 |
| 10 | 37687 | 231 | 0.024642 |

Gold chunk ranks:

| chunk | page | S1 rank | penalized score |
|---:|---:|---:|---:|
| 37047 | 71 | 17 | 0.023385 |
| 37040 | 71 | 25 | 0.021440 |
| 37041 | 71 | 26 | 0.021420 |
| 37039 | 71 | 101 | 0.012049 |
| 37032 | 69 | 139 | 0.009733 |
| 37033 | 69 | 151 | 0.009010 |

Gold chunks in top-6: 0.

## S2 Top 10: Pages <=10 Or >=320 Penalized

| rank | chunk | page | penalized score |
|---:|---:|---:|---:|
| 1 | 36880 | 37 | 0.027056 |
| 2 | 37444 | 155 | 0.026070 |
| 3 | 36983 | 56 | 0.025833 |
| 4 | 36986 | 57 | 0.025320 |
| 5 | 37687 | 231 | 0.024642 |
| 6 | 37011 | 65 | 0.024481 |
| 7 | 37110 | 83 | 0.024359 |
| 8 | 37066 | 76 | 0.024230 |
| 9 | 37019 | 67 | 0.023864 |
| 10 | 37968 | 307 | 0.023810 |

Gold chunk ranks:

| chunk | page | S2 rank | penalized score |
|---:|---:|---:|---:|
| 37047 | 71 | 12 | 0.023385 |
| 37040 | 71 | 19 | 0.021440 |
| 37041 | 71 | 20 | 0.021420 |
| 37039 | 71 | 96 | 0.012049 |
| 37032 | 69 | 135 | 0.009733 |
| 37033 | 69 | 147 | 0.009010 |

Gold chunks in top-6: 0.

## S3: Heading-Path-Aware Penalty

Not evaluable from existing file-only trace data.

The saved trace does not include `meta.heading_path` for fused, dense-before, or
lexical-before candidates. Evaluating this scenario would require either:

- a new retrieval trace that records `heading_path`, or
- a DB read to recover metadata for the candidate chunk IDs.

Both were outside this probe's read-only file-analysis constraint.

## Verdict

The simple front-matter penalty hypothesis does not clear the Stage 3 bar.

No evaluated scenario moved any p04 gold chunk into top-6:

| scenario | gold chunks in top-6 | best gold rank |
|---|---:|---:|
| Original | 0 | 22 |
| S1 pages <=10 x0.5 | 0 | 17 |
| S2 pages <=10 or >=320 x0.5 | 0 | 12 |
| S3 heading_path-aware | not evaluated | not evaluated |

S2 is directionally useful: it moves chunk 37047 from rank 22 to rank 12 and
chunks 37040/37041 from ranks 31/32 to 19/20. But it is not enough to make p04
demo-useful, and it does not approach the success condition of 3+ gold chunks
in top-6.

Conclusion:

- A page-range front-matter/back-matter penalty alone is insufficient.
- The top-6 after S2 is still dominated by non-gold content chunks and a page 37
  TOC/index-style chunk.
- The next retrieval branch should not be only a simple page-range penalty.
- If pursuing deterministic penalties, they need richer evidence-quality
  signals such as heading metadata, content patterns, or index-density features.
- The stronger next branch remains an evidence-quality reranking experiment or
  a more structured penalty experiment with metadata available in trace.
