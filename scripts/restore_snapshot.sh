#!/usr/bin/env bash
# Restore rag_docs and rag_chunks from data/demo_snapshot.sql
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found."
  exit 1
fi
set -a; source .env; set +a

SNAPSHOT="data/demo_snapshot.sql"

if [ ! -f "$SNAPSHOT" ]; then
  echo "ERROR: Snapshot not found at $SNAPSHOT"
  echo "Run 'bash scripts/snapshot.sh' first."
  exit 1
fi

if [ "${1:-}" != "--confirm" ]; then
  echo "WARNING: This will TRUNCATE rag_docs and rag_chunks, then restore from:"
  echo "  $SNAPSHOT ($(wc -l < "$SNAPSHOT") lines, $(du -h "$SNAPSHOT" | cut -f1))"
  echo ""
  echo "Usage: $0 --confirm"
  exit 1
fi

echo "=== Restoring database snapshot ==="
echo ""

echo "1/2 Truncating rag_docs and rag_chunks..."
docker compose -p ammer-mmragv2 exec -T \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" \
  postgres \
  psql -h 127.0.0.1 -U "${POSTGRES_USER}" -d "${RAG_DB}" \
    -c "TRUNCATE rag_chunks, rag_docs CASCADE;"

echo "2/2 Restoring from $SNAPSHOT..."
docker compose -p ammer-mmragv2 exec -T \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" \
  postgres \
  psql -h 127.0.0.1 -U "${POSTGRES_USER}" -d "${RAG_DB}" \
    < "$SNAPSHOT"

echo ""
echo "=== Restore complete ==="

docker compose -p ammer-mmragv2 exec -T \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" \
  postgres \
  psql -h 127.0.0.1 -U "${POSTGRES_USER}" -d "${RAG_DB}" \
    -c "SELECT 'rag_docs' AS table_name, COUNT(*) FROM rag_docs UNION ALL SELECT 'rag_chunks', COUNT(*) FROM rag_chunks;"
