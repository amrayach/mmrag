#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# init_dirs should work even before .env exists
PUID_DEFAULT=1000
PGID_DEFAULT=1000

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

PUID="${PUID:-$PUID_DEFAULT}"
PGID="${PGID:-$PGID_DEFAULT}"

mkdir -p data/inbox data/processed data/assets
mkdir -p n8n/workflows db/init docs scripts
mkdir -p services/pdf-ingest/app services/rag-gateway/app

touch data/.gitkeep

# Ensure FileBrowser user can write
chown -R "${PUID}:${PGID}" data

echo "Directories created and permissions set (data owned by ${PUID}:${PGID})."
