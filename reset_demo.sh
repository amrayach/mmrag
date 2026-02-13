#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

if ! docker compose ps postgres | grep -q "Up"; then
  echo "ERROR: postgres container not running. Start stack first."
  exit 1
fi

echo "Resetting RAG tables and clearing processed/assets..."
docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d rag -c "
  TRUNCATE TABLE rag_chunks RESTART IDENTITY CASCADE;
  TRUNCATE TABLE rag_docs RESTART IDENTITY CASCADE;
"

rm -f data/processed/* || true
rm -f data/assets/* || true

echo "Reset complete."
