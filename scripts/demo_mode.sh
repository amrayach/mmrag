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
    echo "1/4 Stopping rss-ingest (prevents GPU contention)..."
    docker compose stop rss-ingest
    echo "    rss-ingest stopped."

    # 1b. Wait for pdf-ingest to finish any active processing
    echo "    Checking pdf-ingest status..."
    WAITED=0
    while [ "$WAITED" -lt 60 ]; do
      ACTIVE=$(docker compose -p ammer-mmragv2 exec -T pdf-ingest \
        curl -sf http://localhost:8001/ingest/status 2>/dev/null \
        | python3 -c "import json,sys; print(json.load(sys.stdin).get('active_docs',0))" 2>/dev/null || echo "0")
      if [ "$ACTIVE" -eq 0 ] 2>/dev/null; then
        break
      fi
      if [ "$WAITED" -eq 0 ]; then
        echo "    WARNING: pdf-ingest has $ACTIVE active doc(s) — waiting up to 60s..."
      fi
      sleep 5
      WAITED=$((WAITED + 5))
    done
    if [ "$WAITED" -ge 60 ]; then
      echo "    WARNING: pdf-ingest still busy after 60s — proceeding anyway"
    elif [ "$WAITED" -gt 0 ]; then
      echo "    pdf-ingest drained after ${WAITED}s."
    else
      echo "    pdf-ingest idle."
    fi
    echo ""

    # 2. Recreate Ollama so compose GPU/resource settings are applied and
    # stale CPU fallback runners are cleared before the demo starts.
    echo "2/4 Recreating ollama with demo-safe GPU settings..."
    docker compose -p ammer-mmragv2 up -d --force-recreate --no-deps ollama
    echo "    Waiting for ollama API..."
    for _ in $(seq 1 60); do
      if docker compose -p ammer-mmragv2 exec -T ollama ollama list >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    if ! docker compose -p ammer-mmragv2 exec -T ollama ollama list >/dev/null 2>&1; then
      echo "ERROR: ollama did not become ready after restart."
      exit 1
    fi
    echo "    ollama ready."
    echo ""

    # 3. Pre-warm all Ollama models
    echo "3/4 Pre-warming Ollama models..."
    bash scripts/prewarm.sh
    echo ""

    # 4. Quick health verification
    echo "4/4 Verifying core services..."
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
    echo "    n8n         : $N8N_OK (ingestion only)"
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
