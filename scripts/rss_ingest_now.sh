#!/usr/bin/env bash
set -euo pipefail

# Manual trigger for RSS ingestion via n8n webhook
# Requires workflow 03 to be imported and activated in n8n.

code=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:56150/webhook/rss-ingest-now 2>/dev/null || echo "000")
if [ "$code" = "404" ] || [ "$code" = "000" ]; then
  echo "ERROR: Workflow 03 (RSS Ingestion) not active. Import and activate it in n8n first."
  echo "  File: n8n/workflows/03_rss_ingestion.json"
  exit 1
fi
echo "RSS ingestion triggered (HTTP $code). Check logs: docker compose logs -f rss-ingest"
