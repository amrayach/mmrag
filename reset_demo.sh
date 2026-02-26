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

RSS_ONLY=false
if [ "${1:-}" = "--rss-only" ]; then
  RSS_ONLY=true
fi

if [ "$RSS_ONLY" = true ]; then
  echo "Resetting RSS data only (preserving PDF data)..."
  docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d rag -c "
    DELETE FROM rag_docs WHERE filename LIKE 'http%';
  "
  rm -rf data/assets/rss/ || true
  echo "RSS reset complete."
else
  echo "Resetting ALL RAG tables and clearing processed/assets..."
  docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d rag -c "
    TRUNCATE TABLE rag_chunks RESTART IDENTITY CASCADE;
    TRUNCATE TABLE rag_docs RESTART IDENTITY CASCADE;
  "
  rm -f data/processed/* || true
  rm -rf data/assets/* || true
  echo "Full reset complete."
fi
