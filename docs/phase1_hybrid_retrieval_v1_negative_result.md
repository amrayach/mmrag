# Phase 1 Hybrid Retrieval V1 Negative Result

Captured: 2026-05-07

## Summary

Stage 2B V1 implemented and validated a flag-gated hybrid text retrieval path in
`rag-gateway`. The implementation was functionally safe under validation, but it
did not meet the p04 success threshold and should not be shipped as-is.

Final verdict:

- Hybrid V1 is safe behind `RETRIEVAL_MODE=hybrid`.
- Hybrid V1 does not fix the BMW p04 brand-list retrieval failure.
- Do not flip the default from `dense` to `hybrid`.
- Do not ship this V1 implementation without another evidence-quality/ranking step.

## Implementation Tested

- `RETRIEVAL_MODE=dense|hybrid`, default `dense`.
- Text-only hybrid retrieval.
- Primary lexical query via `websearch_to_tsquery('german', query)`.
- OR fallback when lexical results were too sparse.
- Reciprocal Rank Fusion over dense-text and lexical-text candidates.
- Image retrieval remained dense-only and unchanged.
- Final text context remained capped at 6.

Hybrid defaults used in validation:

- `DENSE_TEXT_TOP_K_HYBRID=200`
- `LEXICAL_TEXT_TOP_K=300`
- `RRF_K=60`
- `FINAL_TEXT_TOP_K=6`

## Validation Commands

Commands run during validation:

```bash
docker compose build rag-gateway
docker compose up -d rag-gateway
python3 scripts/demo_e2e_check.py

RAG_TRACE=true RETRIEVAL_MODE=dense docker compose up -d rag-gateway
python3 scripts/diagnose_bmw_p04.py
python3 scripts/audit_bmw_p04_evidence_quality.py

RAG_TRACE=true RETRIEVAL_MODE=hybrid docker compose up -d rag-gateway
python3 scripts/diagnose_bmw_p04.py
python3 scripts/audit_bmw_p04_evidence_quality.py
python3 scripts/demo_e2e_check.py

python3 scripts/eval_run.py \
  --model gemma4:26b \
  --label phase1_hybrid_validation_p04_p07 \
  --only p04_bmw_list_completeness,p07_no_filter_german \
  --rag-trace-path data/rag-traces/retrieval.jsonl

docker compose up -d rag-gateway
python3 scripts/demo_e2e_check.py
curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:56155/v1/diagnostic/retrieval
```

## Dense p04 Baseline

Dense mode used the actual production query path:

- rewritten query: `Liste alle Marken, Geschäftsbereiche oder Beteiligungen auf, die im BMW Group Bericht 2023 erwähnt werden. Bitte vollständige Liste, nicht nach 3 Punkten aufhören.`
- parsed filter: `doc_filter=BMWGroup`
- `VECTOR_DISTANCE_THRESHOLD=0.6`
- text limit: 6
- image limit: 2
- total retrieval before LLM: 94.52 ms

Dense p04 final context remained dominated by BMW front matter / index chunks:

- page 4
- page 325
- page 307
- page 1
- page 8
- page 37

The evidence audit classified the substantive p04 failure as `mixed_failure`:
the only original brand-term match in final context was a table-of-contents
chunk, not an answer-bearing brand-list chunk.

## Hybrid p04 Result

Hybrid mode used the same production query path and `doc_filter=BMWGroup`.

Trace configuration:

- retrieval mode: `hybrid`
- lexical query mode: `or_fallback`
- dense candidates before fusion: 200
- lexical candidates before fusion: 237
- fused candidates captured in trace: 40
- final context chunks: 8
- total retrieval before LLM: 128.61 ms

The six p04 gold chunks were visible in the candidate pools, but none reached
final context.

| Gold chunk | Dense rank | Lexical rank | Fused rank | Final context |
|---:|---:|---:|---:|---|
| 37047 | 65 | 5 | 22 | no |
| 37040 | 38 | 29 | 31 | no |
| 37041 | 37 | 30 | 32 | no |
| 37039 | 79 | 146 | 104 | no |
| 37032 | 147 | 144 | 140 | no |
| 37033 | 182 | 145 | 152 | no |

Hybrid p04 final context was still dominated by BMW index/front-matter chunks:

- page 325
- page 324
- page 1
- page 2
- page 4
- page 8

This missed the expected p04 threshold:

- expected minimum: at least 2 of 6 gold chunks in final text context.
- observed: 0 of 6 gold chunks in final text context.

## p07 Smoke Result

The hybrid p04/p07 eval run completed successfully:

- run directory: `data/eval/runs/20260507_185509__phase1_hybrid_validation_p04_p07`
- trace records: 2
- model: `gemma4:26b`

p07 final context under hybrid contained:

- 3 PDF chunks
- 3 RSS chunks
- 0 images

p07 latency:

- TTFT: 1475 ms
- total latency: 11300 ms
- answer length: 2184 chars
- sources: 6

p07 looked acceptable as a smoke test, but it was not decisive enough to justify
shipping hybrid V1 when p04 still failed the target threshold.

## Latency Notes

Observed retrieval timings:

- dense p04 retrieval before LLM: 94.52 ms
- hybrid p04 retrieval before LLM: 128.61 ms
- p04 eval total response latency under hybrid: 3193 ms
- p07 eval total response latency under hybrid: 11300 ms

Hybrid added measurable retrieval overhead, mainly from wider vector search and
lexical search, but the overhead was not the blocking issue. The failure was
ranking quality.

## Artifacts

Relevant artifacts:

- `data/eval/runs/20260507_185509__phase1_hybrid_validation_p04_p07`
- `data/eval/phase0_baseline/bmw_p04_diagnostic.json`
- `data/eval/phase0_baseline/bmw_p04_diagnostic.md`
- `data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.json`
- `data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.md`

Large trace payloads are not copied into this report.

## Interpretation

Hybrid V1 improved candidate visibility slightly, but not enough to overcome the
BMW index/front-matter chunks that outrank the answer-bearing chunks.

The issue is now more specific than raw lexical recall:

- the retriever can see relevant chunks;
- answer-bearing chunks still rank below weaker TOC/index/front-matter chunks;
- the next branch should address evidence quality and ranking, not just lexical
  candidate collection.

Likely next branches to plan:

- a lightweight text reranker over dense/hybrid candidates;
- deterministic TOC/front-matter/index suppression or penalty;
- structural metadata prefixing for PDF chunks;
- a narrow list-completeness retrieval route.

Do not ship hybrid V1 as-is.
