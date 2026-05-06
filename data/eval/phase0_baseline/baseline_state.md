# Phase 0.0 — Baseline state snapshot

Captured before any Phase 0 code changes that could mask current failure modes.
This is the "before" reference. All later Phase 0 evidence is compared against it.

## Capture metadata

- **Captured at:** 2026-05-06T13:57:00+02:00
- **Captured by:** Phase 0 retrieval diagnostics — staged plan, Phase 0 only
- **Repo root:** `/srv/projects/ammer/mmrag-n8n-demo-v2`
- **Git HEAD:** `b31356c68ee26eba7c11f8c309ae75f2a809a189`
- **Last commit:** `b31356c — docs: refresh runtime docs and control center` (2026-05-06 03:03:17 +0200)
- **Working tree:** dirty (see uncommitted changes below)

### Uncommitted changes at capture time

```
 M .gitignore
 M CLAUDE.md
 M MANUAL_STEPS.md
 M docker-compose.yml
 M docs/DEMO_REVIEW_AGENDA.md
 M scripts/demo_mode.sh
 M scripts/demo_readiness_check.sh
 M scripts/eval_run.py
 M scripts/prewarm.sh
 M services/controlcenter/app/static/js/pages/overview.js
 M services/rag-gateway/app/context.py
?? data/eval/runs/20260505_200547__think_false_sanity/
?? data/eval/runs/20260505_224657__qwen3_6_27b/
?? data/eval/runs/20260505_232143__qwen3_30b/
?? data/eval/runs/20260505_234935__mistral_small3_2_24b/
?? data/eval/runs/20260506_003015__qwen2_5_32b/
?? data/eval/runs/20260506_010918__command_r_35b/
?? data/eval/runs/20260506_013422__qwen3_30b_v0231/
?? data/eval/runs/20260506_014045__qwen3_6_27b_v0231/
?? data/eval/runs/20260506_015220__gemma4_26b_smoke/
?? data/eval/runs/20260506_015332__gemma4_26b/
?? data/eval/runs/20260506_022253__gemma4_31b_smoke/
?? data/eval/runs/20260506_022922__post_promote_gemma4_26b_smoke/
?? scripts/TechVision_AG_Jahresbericht_2025.pdf
```

## Compose project identity

- **Compose project name (canonical):** `ammer-mmragv2`
  Source: `docker-compose.yml` top-level `name:` field. The `.env` does not
  define `COMPOSE_PROJECT_NAME`; the compose-level `name:` wins.
- **Container prefix:** `ammer_mmragv2_`
- **Postgres host port:** `127.0.0.1:56154 → container 5432`
  Source: `docker-compose.yml` `ports: ["127.0.0.1:${PORT_PG}:5432"]`,
  `.env` `PORT_PG=56154`
- **rag-gateway internal:** no host binding; reached internally from gateway,
  pdf-ingest, rss-ingest, controlcenter, n8n via the project network.

## Retrieval-relevant configuration at capture time

Sourced from `.env` and `docker-compose.yml` (rag-gateway service section).

| Variable                    | Value                | Source              |
|-----------------------------|----------------------|---------------------|
| `DEFAULT_MODEL`             | `gemma4:26b`         | compose: `${OLLAMA_TEXT_MODEL}` from `.env` |
| `OLLAMA_TEXT_MODEL`         | `gemma4:26b`         | `.env`              |
| `OLLAMA_VISION_MODEL`       | `qwen2.5vl:7b`       | `.env`              |
| `OLLAMA_EMBED_MODEL`        | `bge-m3`             | `.env`              |
| `VECTOR_DISTANCE_THRESHOLD` | `0.6`                | compose hard-coded  |
| `OLLAMA_BASE_URL`           | `http://ollama:11434` | `.env`             |
| `CONTEXT_MODE`              | `direct` (code default) | `services/rag-gateway/app/main.py:35` |
| `RAG_DB`                    | `rag`                | `.env`              |
| `PUBLIC_ASSETS_BASE_URL`    | `https://spark-e010.tail907fce.ts.net:8454` | `.env` |

Notes:
- The `services/rag-gateway/app/main.py:33` Python-level fallback for
  `DEFAULT_MODEL` is `qwen2.5:7b-instruct`, but the compose env overrides it to
  `gemma4:26b` at runtime — this matches the post-promote state from
  2026-05-06.
- `VECTOR_DISTANCE_THRESHOLD=0.6` is cosine **distance**, not similarity.
  The SQL pre-filter keeps rows with cosine **score > 0.4**.
- `image_score_min` defaults are baked into `services/rag-gateway/app/context.py`:
  `0.45` for image-intent queries, `0.55` otherwise. Same file: image-query
  reserved 4+4 text/image slots, non-image-query 6+2.

## Reference baseline run (production retrieval, current code)

The most recent full 12-prompt eval run against the current production stack
(gemma4:26b, Ollama 0.23.1, post-ODL chunks, post-bge-m3 embeddings) is:

- **Run dir:** `data/eval/runs/20260506_015332__gemma4_26b/`
- **Started:** `2026-05-05T23:53:32+00:00`
- **Model:** `gemma4:26b`
- **Gateway:** `http://127.0.0.1:56155`
- **Stream:** true, temp 0.2, max_tokens 800
- **Prompts:** 12, **Turns:** 13, **Errors:** 0
- **Avg TTFT:** 1084 ms, **Avg total:** 6971 ms
- **Avg answer chars:** 1148, **Avg sources:** 6.0, **Avg images:** 1.3
- **p04 file:** `data/eval/runs/20260506_015332__gemma4_26b/p04_bmw_list_completeness.json`

This run is the Phase 0.0 reference snapshot for "current production retrieval
behavior". After Phase 0 completes (no behavior changes; flag-gated tracing
only), a fresh run with `RAG_TRACE=true` and `--label phase0_baseline` should
match this run's answer bodies/sources/images bit-equivalently when the trace
flag is left at default.

## Known failure state being preserved

- BMW PDF text chunks: 486 with `embedding IS NULL` and
  `meta.embedding_error = "ollama_embed_failed"`. These are silently excluded
  from retrieval by the `WHERE embedding IS NOT NULL` SQL pre-filter in
  `services/rag-gateway/app/context.py:176`.
- p04 list-completeness symptom: previous evaluations across 7 model
  candidates show the BMW brand-list is incomplete (typically ≤4 brands
  surfaced: BMW, MINI, Rolls-Royce, BMW Motorrad). Likely retrieval-side, not
  model-side — Phase 0.4 will classify the failure mode.
- p07 unfiltered German query: known weakness — RSS chunks dominate PDF chunks
  in retrieval ranking when no `@filter` is supplied.

## What Phase 0 will and will not change

Phase 0 is diagnostic only:
- adds `RAG_TRACE` flag (default off; off ⇒ byte-identical production behavior)
- adds per-stage timing instrumentation (recorded in trace; no behavior delta)
- adds read-only diagnostic scripts under `scripts/`
- adds dry-run-default missing-embedding backfill (writes only with `--execute`)
- adds gold-chunk scaffold and retrieval-metric scaffold under `data/eval/`
- adds Phase 1 prep doc under `docs/plans/`

Phase 0 will **not**:
- change the retrieval algorithm
- change the embedding model or re-embed any chunks
- change schema (no DDL)
- change the generator model
- change SSE / OpenAI-compatible API contract
- expose new ports, change port bindings, or add Tailscale Funnel rules
