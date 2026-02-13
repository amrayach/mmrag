#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

echo "== Health: containers =="
docker compose ps

echo "== Health: postgres =="
docker compose exec -T postgres pg_isready -U "${POSTGRES_USER}" -d postgres

echo "== Health: n8n UI =="
if curl -fsS "http://127.0.0.1:${PORT_N8N}/" 2>/dev/null | grep -qi "n8n"; then
  echo "OK: n8n UI responding"
else
  echo "WARNING: n8n UI not responding as expected"
fi

echo "== Health: OpenWebUI =="
curl -fsS "http://127.0.0.1:${PORT_OPENWEBUI}/" >/dev/null && echo "OK: OpenWebUI responding"

echo "== Health: Adminer =="
curl -fsS "http://127.0.0.1:${PORT_ADMINER}/" >/dev/null && echo "OK: Adminer responding"

echo "== Health: Assets =="
curl -fsS "http://127.0.0.1:${PORT_ASSETS}/" >/dev/null 2>&1 && echo "OK: Assets server responding" || echo "NOTE: Assets empty is fine"

echo "== Health: rag-gateway container =="
docker compose exec -T rag-gateway curl -fsS http://127.0.0.1:8000/health >/dev/null && echo "OK: rag-gateway /health"

echo "== Health: pdf-ingest container =="
docker compose exec -T pdf-ingest python -c "import requests; print(requests.get('http://127.0.0.1:8001/health').json())" >/dev/null 2>&1 && echo "OK: pdf-ingest /health" || echo "WARNING: pdf-ingest health check failed"

echo "Health checks complete."
