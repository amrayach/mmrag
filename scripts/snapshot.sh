#!/usr/bin/env bash
# Dump rag_docs and rag_chunks to data/demo_snapshot.sql
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found."
  exit 1
fi
set -a; source .env; set +a

SNAPSHOT="data/demo_snapshot.sql"

echo "=== Creating database snapshot ==="
echo "Tables: rag_docs, rag_chunks"
echo "Target: $SNAPSHOT"
echo ""

docker compose -p ammer-mmragv2 exec -T \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" \
  postgres \
  pg_dump -h 127.0.0.1 -U "${POSTGRES_USER}" -d "${RAG_DB}" \
    --table=rag_docs --table=rag_chunks \
    --no-owner --no-privileges \
  > "$SNAPSHOT"

LINES=$(wc -l < "$SNAPSHOT")
SIZE=$(du -h "$SNAPSHOT" | cut -f1)

echo "Snapshot saved: $SNAPSHOT"
echo "  Size:  $SIZE"
echo "  Lines: $LINES"
