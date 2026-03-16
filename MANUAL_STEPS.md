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

## 4) Configure Reverse Proxy or Tailscale Serve

All services bind to `127.0.0.1` only. To access from other machines, set up a reverse proxy or Tailscale Serve:

```bash
# Example with Tailscale Serve (adjust ports as needed):
tailscale serve --bg --https=8450 http://127.0.0.1:56150   # n8n
tailscale serve --bg --https=8451 http://127.0.0.1:56151   # OpenWebUI
tailscale serve --bg --https=8452 http://127.0.0.1:56152   # FileBrowser
tailscale serve --bg --https=8453 http://127.0.0.1:56153   # Adminer
tailscale serve --bg --https=8454 http://127.0.0.1:56157   # Assets
tailscale serve --bg --https=8455 http://127.0.0.1:56156   # Control Center
```

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

## 5) OpenWebUI Provider

In OpenWebUI Admin panel:
- Add an OpenAI-compatible provider:
  - Base URL: `http://rag-gateway:8000/v1`
  - API key: any non-empty string (e.g. `sk-dummy`)

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

3. **Model Selection** — set the default model to the rag-gateway model (should appear as `qwen2.5:7b-instruct` or whatever `DEFAULT_MODEL` is set to in `.env`).

These starter questions are designed to showcase all four capabilities in the demo: PDF retrieval, RSS feeds, multimodal images, and cross-source reasoning.

## 7) Adminer (Optional)

- URL: `http://127.0.0.1:56153`
- System: PostgreSQL
- Server: `postgres`
- Username / Password: from `.env`
- Database: `rag`

---

## Deployment Deviations from Spec (v2.4) — 21 items

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
| D16 | `OLLAMA_MAX_LOADED_MODELS=1` | Changed to `3` | DGX Spark has 128 GB unified memory — keeps all 3 models loaded (~11 GB total), eliminates model swap latency |
| D17 | No RSS image backfill | Added `/ingest/backfill-images` endpoint | Adds image chunks to RSS articles ingested before captioning was enabled. Filters SVGs, tracking pixels, and images < 5 KB |
| D18 | Serial PDF ingestion (`OLLAMA_NUM_PARALLEL=1`, lock file) | Parallel pipeline: `OLLAMA_NUM_PARALLEL=3`, `ThreadPoolExecutor(2)` for concurrent docs, 3 caption workers with bounded queue, batch embeddings (`/api/embed`, 10/batch), image filtering (<150px, <5KB, doc-scoped dedup), PyMuPDF shrink downscaling, auto file watcher | ~8-9x speedup for bulk PDF prep. See `docs/plans/2026-03-06-fast-pdf-ingestion-design.md` |
| D18a | `/ingest/upload` blocks until ingestion complete | Returns `202 Accepted`, saves to inbox, defers to file watcher | Prevents upload timeouts and lock contention |
| D18b | `/ingest/scan` blocks until all PDFs processed | Returns immediately after submitting to thread pool | Non-blocking; n8n cron acts as fallback to file watcher |
| D19 | No unified control UI | Control Center (11th container) on port 56156/8455 | Single-pane-of-glass: dashboard, services, ingestion, demo mode, RAG playground, docs, system info |
