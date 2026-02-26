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
   - `01_chat_brain.json` — handles chat requests via webhook
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
```

**Client prerequisites:** Tailscale must be running and connected on the accessing device. Verify with `tailscale status`.

**Serve persistence:** Tailscale Serve rules persist across daemon restarts on Linux (stored in Tailscale state). To verify after a server reboot, run `tailscale serve status`.

**Quick self-diagnosis:**
```bash
# Verify serve rules are active
tailscale serve status

# Test all endpoints from the server
for port in 8450 8451 8452 8453 8454; do
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

## 6) Adminer (Optional)

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
