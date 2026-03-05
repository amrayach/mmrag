#!/usr/bin/env bash
# Demo Mode — stops background GPU consumers and pre-warms models for live demos
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found."
  exit 1
fi
set -a; source .env; set +a

TAILNET_HOST="spark-e010.tail907fce.ts.net"

case "${1:-}" in
  start)
    echo "=== Activating Demo Mode ==="
    echo ""

    # 1. Stop RSS ingest to free GPU for interactive queries
    echo "1/3 Stopping rss-ingest (prevents GPU contention)..."
    docker compose stop rss-ingest
    echo "    rss-ingest stopped."

    # 2. Pre-warm all Ollama models
    echo "2/3 Pre-warming Ollama models..."
    bash scripts/prewarm.sh
    echo ""

    # 3. Quick health verification
    echo "3/3 Verifying core services..."
    GW_OK=$(curl -sf http://127.0.0.1:56155/health 2>/dev/null && echo "ok" || echo "FAIL")
    N8N_OK=$(curl -sf http://127.0.0.1:56150/healthz 2>/dev/null && echo "ok" || echo "FAIL")
    OW_OK=$(curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1:56151 2>/dev/null || echo "000")

    echo ""
    echo "========================================"
    echo "       DEMO MODE ACTIVE"
    echo "========================================"
    echo ""
    echo "  Services:"
    echo "    rag-gateway : $GW_OK"
    echo "    n8n         : $N8N_OK"
    echo "    OpenWebUI   : HTTP $OW_OK"
    echo "    rss-ingest  : STOPPED (GPU freed)"
    echo ""
    echo "  Tailnet URLs:"
    echo "    Chat    : https://${TAILNET_HOST}:8451"
    echo "    n8n     : https://${TAILNET_HOST}:8450"
    echo "    Files   : https://${TAILNET_HOST}:8452"
    echo "    Assets  : https://${TAILNET_HOST}:8454"
    echo "    Adminer : https://${TAILNET_HOST}:8453"
    echo ""
    echo "  Run 'make demo-stop' when done."
    echo "========================================"
    ;;

  stop)
    echo "=== Deactivating Demo Mode ==="
    echo ""
    echo "Starting rss-ingest..."
    docker compose start rss-ingest
    echo ""
    echo "========================================"
    echo "  Demo Mode Deactivated"
    echo "  rss-ingest is running again."
    echo "========================================"
    ;;

  *)
    echo "Usage: $0 {start|stop}"
    echo ""
    echo "  start — Stop rss-ingest, pre-warm models, show dashboard"
    echo "  stop  — Restart rss-ingest"
    exit 1
    ;;
esac
