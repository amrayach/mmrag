# Manual Steps (Post-Deployment Configuration)

These steps must be done after `docker compose up -d --build` succeeds.

## 1) Create .env

Copy `.env.example` to `.env` and generate secrets:

```bash
cp .env.example .env
# Set a strong POSTGRES_PASSWORD:
#   openssl rand -base64 24
# Set N8N_ENCRYPTION_KEY (64 hex chars):
#   openssl rand -hex 32
# Set PUID/PGID to your Linux user's uid/gid:
#   id -u && id -g
```

## 2) n8n Setup

1. Open n8n at `http://127.0.0.1:56150`
2. Create an owner account (first-time setup wizard)
3. Add a PostgreSQL credential:
   - Name: `RAG Postgres`
   - Host: `postgres`, Port: `5432`
   - Database: `rag`
   - User / Password: from your `.env`
   - SSL: disabled
4. Import workflows from `n8n/workflows/`:
   - `01_chat_brain.json` — context retrieval via webhook (6 nodes: embed, vector search, build context)
   - `02_ingestion_factory.json` — scheduled PDF ingestion
   - `03_rss_ingestion.json` — scheduled RSS feed ingestion (every 8h + manual webhook)
5. Activate all three workflows

## 3) Change FileBrowser Password

- Open FileBrowser at `http://127.0.0.1:56152`
- Default login: `admin` / `admin`
- **Change the password immediately** (Settings > Users)

## 4) Configure Reverse Proxy, Tailscale Serve, or Approved Hybrid Funnel

All host ports bind to `127.0.0.1` only. To access from other machines on the tailnet, set up a reverse proxy or Tailscale Serve. These commands change system state and require explicit operator approval before execution.

```bash
# Tailnet-only Tailscale Serve example for standard internal operation:
tailscale serve --bg --https=8450 http://127.0.0.1:56150   # n8n
tailscale serve --bg --https=8451 http://127.0.0.1:56151   # OpenWebUI
tailscale serve --bg --https=8452 http://127.0.0.1:56152   # FileBrowser
tailscale serve --bg --https=8453 http://127.0.0.1:56153   # Adminer
tailscale serve --bg --https=8454 http://127.0.0.1:56157   # Assets
tailscale serve --bg --https=8455 http://127.0.0.1:56156   # Control Center
```

**Option 3C hybrid demo mode:** the default rule remains Serve-only/no Funnel. The approved exception allows Funnel only for the hybrid public demo, only after explicit operator approval, and only for demo-site. Do not expose OpenWebUI directly in hybrid mode; remove any direct OpenWebUI Serve/Funnel rule first. The S6/operator step must expose demo-site as the public root and verify the URL from off-tailnet.

**Client prerequisites:** Tailscale must be running and connected on the accessing device. Verify with `tailscale status`.

**Serve persistence:** Tailscale Serve rules persist across daemon restarts on Linux (stored in Tailscale state). To verify after a server reboot, run `tailscale serve status`.

**Quick self-diagnosis:**
```bash
# Verify serve rules are active
tailscale serve status

# Test all endpoints from the server
for port in 8450 8451 8452 8453 8454 8455; do
  echo -n ":$port -> "
  curl -k -s -o /dev/null -w "%{http_code}" https://spark-e010.tail907fce.ts.net:$port
  echo
done

# If a client can't connect, have them run on their machine:
tailscale status                                    # Must show "active"
nslookup spark-e010.tail907fce.ts.net               # Must resolve to 100.77.150.62
curl -k https://spark-e010.tail907fce.ts.net:8450   # Test directly
# macOS DNS cache flush: sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder
```

For hybrid mode, also confirm that direct OpenWebUI exposure is absent and that the demo-site root is the only public entrypoint.

## 5) OpenWebUI Provider

In OpenWebUI Admin panel:
- Add an OpenAI-compatible provider:
  - Base URL: `http://rag-gateway:8000/v1`
  - API key: any non-empty string (e.g. `sk-dummy`)

For Option 3C hybrid mode, OpenWebUI authentication is configured through trusted headers but still requires a session cookie. demo-site performs the `/api/openwebui/start` bootstrap by validating `demo_session`, pre-creating the reviewer user when admin credentials are configured, signing in with trusted headers, and relaying OpenWebUI `Set-Cookie` headers to the browser. Header-only requests do not authenticate.

Rollback for hybrid mode: set `DEMO_SITE_OPENWEBUI_ENABLED=false`, restart the affected service after approval, and use the classic demo-site chat (`/classic`) backed by the existing `/api/chat` endpoint.

## 6) OpenWebUI Welcome Banner & Starter Questions

In OpenWebUI **Admin > Settings > Interface**:

1. **Welcome Banner Text** (set under "Default Prompt Suggestions"):
   ```
   MMRAG Multi-Source AI Assistant — Ask questions about your documents and live news feeds.
   ```

2. **Starter Questions** — add exactly these 4 prompts:
   - `Was steht im Handbuch zur Wartung und Pflege?`
     *(PDF query — tests document retrieval with page references)*
   - `Was sind die neuesten Technologie-Nachrichten?`
     *(RSS query — tests live news feed retrieval with source links)*
   - `Zeige mir Bilder aus den Dokumenten und beschreibe sie`
     *(Multimodal query — tests image retrieval and captioning)*
   - `Vergleiche die Informationen aus dem Handbuch mit aktuellen Nachrichten`
     *(Cross-source query — tests multi-source synthesis)*

3. **Model Selection** — set the default model to the rag-gateway model (should appear as `gemma4:26b` or whatever `DEFAULT_MODEL` is set to in `.env`).

These starter questions are designed to showcase all four capabilities in the demo: PDF retrieval, RSS feeds, multimodal images, and cross-source reasoning.

## 7) Adminer (Optional)

- URL: `http://127.0.0.1:56153`
- System: PostgreSQL
- Server: `postgres`
- Username / Password: from `.env`
- Database: `rag`

---

## Deployment Deviations from Spec (v2.4)

| # | Spec Item | Deviation | Reason |
|---|-----------|-----------|--------|
| D1 | `supabase/postgres:latest` | Changed to `supabase/postgres:15.14.1.081` | No `latest` tag exists on DockerHub |
| D2 | FileBrowser `user: "${PUID}:${PGID}"` | Removed | Docker volumes are root-owned; container crashed with permission denied |
| D3 | `from pgvector import Vector` in pdf-ingest | Removed; `Vector(embedding)` -> `embedding` | pgvector 0.3.6 doesn't export `Vector`; `register_vector()` handles list->vector natively |
| D4 | PUID/PGID = 1000:1000 | Changed to match actual host user | Actual uid/gid varies per system |
| D5 | DB init via docker-entrypoint-initdb.d | Applied manually via TCP psql | supabase pg_hba.conf blocks local peer auth for rag_user |
| D6 | Webhook nodes without `webhookId` | Added `webhookId` UUIDs | n8n v1.102.0 requires `webhookId` for clean webhook URL registration |
| D7 | httpRequest nodes use v3 params | Converted to v4 params (`sendBody`, `contentType`, etc.) | Spec used `typeVersion: 4` but with v3-style parameters |
| D8 | Postgres credential SSL not specified | Disabled SSL | supabase/postgres container does not use SSL internally |
| D9 | `n8n-nodes-base.function` typeVersion 2 | Replaced with `n8n-nodes-base.code` | Function node removed in n8n v1.102.0 |
| D10 | `n8n-nodes-base.cron` typeVersion 1 | Replaced with `n8n-nodes-base.scheduleTrigger` | Cron node deprecated in n8n v1.x |
| D11 | Expression fields without `=` prefix | Added `=` prefix | n8n v1.x requires `=` prefix for `{{ }}` expressions |
| D12 | httpRequest jsonBody with inline `{{ }}` | Moved to Code nodes with `JSON.stringify` | Inline `{{ }}` in JSON breaks on user input with quotes/newlines |
| D13 | Code node `$json.query` for webhook body | Changed to `$json.body.query` | Webhook v2 wraps POST body in `$json.body` |
| D14 | LLM generation in n8n Chat Brain | Moved to rag-gateway (Phase 2 streaming) | Enables true token streaming (Ollama NDJSON → OpenAI SSE). n8n now returns context only (6 nodes). |
| D15 | Assets nginx with default config | Custom `nginx/assets.conf` with gallery | Added JSON autoindex at `/api/files` and HTML gallery as index page |
| D16 | `OLLAMA_MAX_LOADED_MODELS=1` | Changed to `3` | DGX Spark has 128 GB unified memory — keeps the text, vision, and embedding models loaded (~28 GB total with `gemma4:26b`), reducing model swap latency |
| D17 | No RSS image backfill | Added `/ingest/backfill-images` endpoint | Adds image chunks to RSS articles ingested before captioning was enabled. Filters SVGs, tracking pixels, and images < 5 KB |
| D18 | Serial PDF ingestion (`OLLAMA_NUM_PARALLEL=1`, lock file) | Parallel pipeline: `OLLAMA_NUM_PARALLEL=3`, `ThreadPoolExecutor(2)` for concurrent docs, 3 caption workers with bounded queue, batch embeddings (`/api/embed`, 10/batch), image filtering (<150px, <5KB, doc-scoped dedup), PyMuPDF shrink downscaling, auto file watcher | ~8-9x speedup for bulk PDF prep. See `docs/plans/2026-03-06-fast-pdf-ingestion-design.md` |
| D18a | `/ingest/upload` blocks until ingestion complete | Returns `202 Accepted`, saves to inbox, defers to file watcher | Prevents upload timeouts and lock contention |
| D18b | `/ingest/scan` blocks until all PDFs processed | Returns immediately after submitting to thread pool | Non-blocking; n8n cron acts as fallback to file watcher |
| D19 | No unified control UI | Control Center (11th container) on port 56156/8455 | Single-pane-of-glass: dashboard, services, ingestion, demo mode, RAG playground, docs, system info |
| D24 | PyMuPDF text extraction in pdf-ingest | Replaced with `opendataloader-pdf==2.4.1` local mode; section-based chunking with heading breadcrumbs replaces flat 1500-char page chunks | OpenJDK 17 JRE runs in pdf-ingest. Bounding boxes, page sizes, heading paths, element ids, element types, extractor provenance, and split strategy are stored in `rag_chunks.meta`. PyMuPDF remains for image post-processing, dimension checks, and fallback. Reprocessing uses `scripts/reprocess_pdfs.sh --confirm` after a DB snapshot and `data/assets/_pre_opendataloader_<ts>/` asset quarantine. The May 5, 2026 rollout reprocessed all five PDFs and produced 1,648 PDF chunks with `meta.bbox`; snapshot `data/demo_snapshot_pre_opendataloader_20260505_172446.sql`, asset quarantine `data/assets/_pre_opendataloader_20260505_172446/`. Embedding (`bge-m3`) and vision captioning (`qwen2.5vl:7b`) unchanged. BMW Group has 486 noisy text chunks stored without embeddings and flagged with `meta.embedding_error`. |
| D25 | `qwen2.5:7b-instruct` text-generation default on `ollama/ollama:0.18.0` | Promoted `gemma4:26b` as the text-generation default and pinned `ollama/ollama:0.23.1` | A seven-candidate eval showed `gemma4:26b` was the first model to improve answer quality while reducing average total latency (7.0s vs 9.8s for the 7B baseline). Ollama 0.23.1 is required for the Gemma 4 manifest. Embedding and vision models remain `bge-m3` and `qwen2.5vl:7b`. |
| D26 | Demo mode only prewarmed models | Demo mode now recreates the Ollama container with demo-performance GPU settings, prewarms all three production models for 1h, and fails if any required model is missing from GPU residency | Prevents silent CPU fallback during demos. Settings prioritize one smooth live answer at a time on the GB10: `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=3`, `OLLAMA_CONTEXT_LENGTH=4096`, `OLLAMA_LLM_LIBRARY=cuda_v13`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_FLASH_ATTENTION=true`, no artificial Ollama VRAM cap. |

### Post-ODL Baseline & BMW Assessment (2026-05-05)

A 12-prompt fixed eval was run against the post-ODL corpus with the then-current baseline text model (`qwen2.5:7b-instruct`, temp=0.2, prewarmed). Run dir: `data/eval/runs/20260505_190437__baseline_post_odl/`. Harness: `scripts/eval_run.py` + `data/eval/prompts.json`.

Headline numbers: 13/13 turns succeeded, avg TTFT 877 ms, avg total latency 9.8 s, avg 6 sources / 2 images per response.

**BMW unembedded-chunks decision: accepted as documented limitation, no fix planned.**
Evidence:
- p01 (BMW Kennzahlen) retrieved €29.689 Mio Bruttoergebnis and €18.482 Mio Ergebnis vor Finanzergebnis from page 57 with 8 BMW sources.
- p05 (BMW Tabellenzahlen) retrieved 5 distinct table rows from page 10 with concrete numerical content.
- p04 (BMW list-completeness) returned a short list (4 items). The May 6 model A/B later showed this is primarily a retrieval/list-page recall issue, not a model-size issue.

The 486 unembedded chunks mostly correspond to table/index/layout regions that BMW's PDF structure produces with high `�` density. They retain `meta.bbox` and remain inspectable; their information is also reachable via embedded text chunks and image captions. If a future eval surfaces a BMW question that fails specifically because of unembedded content, revisit by adding a `�`-density text-cleanup pre-filter or routing affected pages through the PyMuPDF fallback.

**RSS-vs-PDF retrieval (p07):** the unfiltered prompt "Was sagen die deutschen Quellen zum Thema Nachhaltigkeit?" returned BMW page 78 + Siemens Nachhaltigkeit page 28 as the top-2 sources. The earlier project-truth note that "unfiltered PDF queries get outscored by RSS text chunks" may be stale post-ODL and should be re-verified before being relied on for demo guidance.

### Text-Model A/B And gemma4 Promotion (2026-05-06)

The text-model A/B phase is complete. The eval harness tested the 7B baseline plus `qwen3.6:27b`, `qwen3:30b`, `mistral-small3.2:24b-instruct-2506-q4_K_M`, `qwen2.5:32b-instruct-q4_K_M`, `command-r:35b-08-2024-q4_K_M`, `gemma4:26b`, and a `gemma4:31b` smoke.

`gemma4:26b` was promoted as the production text model. It produced clean German answers with no thinking leakage, no p04 plant hallucination or repetition loop, byte-near-identical p01/p12 stability, and better latency than the 7B baseline: avg TTFT 1,084 ms, avg total 7.0s vs 9.8s baseline. Runtime is now `OLLAMA_TEXT_MODEL=gemma4:26b` with `ollama/ollama:0.23.1`.

Rejected candidates remain useful evidence but are not production defaults: `qwen3:30b` leaked reasoning into `/api/chat`, `qwen3.6:27b` was faithful but slow and over-conservative, `mistral-small3.2` hallucinated and looped on p04, `qwen2.5:32b` was safe but too slow, `command-r:35b` had a basic BMW refusal, and `gemma4:31b` was too slow in smoke testing.

The remaining high-value improvement is retrieval-side: BMW p04 list completeness fails because the relevant brand/list chunks do not reliably surface in top-k. Fix with lexical recall, reranking, or targeted chunking before considering another model swap.
