#!/usr/bin/env bash
# Reprocess all PDFs in data/processed/ through the OpenDataLoader pipeline.
# Creates a DB snapshot, quarantines old PDF assets, removes old rows for those
# doc_ids, and moves PDFs back to inbox for the watcher.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" != "--confirm" ]]; then
  echo "Refusing to run without --confirm."
  echo "This quarantines assets and deletes chunks/docs for all PDFs in data/processed/."
  exit 1
fi

[[ -f .env ]] || { echo "ERROR: .env not found"; exit 1; }
set -a; source .env; set +a

PROJECT="ammer-mmragv2"
PSQL=(docker compose -p "$PROJECT" exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres
      psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$RAG_DB" -At)

status=$(docker compose -p "$PROJECT" exec -T pdf-ingest \
           curl -sf http://localhost:8001/ingest/status)
active=$(echo "$status" | python3 -c "import json,sys; print(json.load(sys.stdin)['active_docs'])")
qsize=$(echo "$status" | python3 -c "import json,sys; print(json.load(sys.stdin)['caption_queue_size'])")
if (( active > 0 || qsize > 0 )); then
  echo "Refusing: active_docs=$active caption_queue_size=$qsize"
  exit 1
fi

mapfile -t pdfs < <(find data/processed -maxdepth 1 -name '*.pdf' -printf '%f\n' | sort)
[[ ${#pdfs[@]} -gt 0 ]] || { echo "No PDFs in data/processed/"; exit 1; }

doc_ids=()
for fn in "${pdfs[@]}"; do
  did=$(python3 -c "import uuid,sys; print(uuid.uuid5(uuid.NAMESPACE_URL, 'mmrag:' + sys.argv[1]))" "$fn")
  doc_ids+=("$did")
done

ts=$(date +%Y%m%d_%H%M%S)
snap="data/demo_snapshot_pre_opendataloader_${ts}.sql"
quarantine="_pre_opendataloader_${ts}"

echo "PDFs to reprocess (${#pdfs[@]}):"
for i in "${!pdfs[@]}"; do
  printf '  %s  doc_id=%s\n' "${pdfs[$i]}" "${doc_ids[$i]}"
done
echo ""
echo "Snapshot:   $snap"
echo "Quarantine: data/assets/${quarantine}/"
echo ""
read -r -p "Type literal 'yes' to continue: " answer
if [[ "$answer" != "yes" ]]; then
  echo "Aborted."
  exit 1
fi

docker compose -p "$PROJECT" exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$RAG_DB" \
    --table=rag_docs --table=rag_chunks --no-owner --no-privileges \
  > "$snap"
[[ -s "$snap" ]] || { echo "Snapshot empty; aborting before deletes"; exit 1; }
echo "Snapshot saved: $snap ($(du -h "$snap" | cut -f1))"

docker compose -p "$PROJECT" exec -T pdf-ingest mkdir -p "/kb/assets/${quarantine}"
for did in "${doc_ids[@]}"; do
  docker compose -p "$PROJECT" exec -T pdf-ingest sh -c \
    "find /kb/assets -maxdepth 1 -name '${did}_p*_i*.*' -exec mv -t /kb/assets/${quarantine} {} +" \
    || true
  "${PSQL[@]}" -c "DELETE FROM rag_chunks WHERE doc_id='$did';" >/dev/null
  "${PSQL[@]}" -c "DELETE FROM rag_docs WHERE doc_id='$did';" >/dev/null
done

mv data/processed/*.pdf data/inbox/
echo "Reprocess queued."
echo "Quarantine: data/assets/${quarantine}/"
echo "Watch: docker compose -p $PROJECT logs -f pdf-ingest"
