#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

KEEP_ALIVE="1h"

echo "1/3 Pre-warming vision model (${OLLAMA_VISION_MODEL}, keep_alive ${KEEP_ALIVE})..."
docker compose exec -T ollama curl -sf http://localhost:11434/api/generate -d "{
  \"model\": \"${OLLAMA_VISION_MODEL}\",
  \"prompt\": \"Describe this test.\",
  \"keep_alive\": \"${KEEP_ALIVE}\",
  \"stream\": false
}" >/dev/null
echo "    Vision model loaded."

echo "2/3 Pre-warming embedding model (${OLLAMA_EMBED_MODEL}, keep_alive ${KEEP_ALIVE})..."
docker compose exec -T ollama curl -sf http://localhost:11434/api/embeddings -d "{
  \"model\": \"${OLLAMA_EMBED_MODEL}\",
  \"prompt\": \"test\",
  \"keep_alive\": \"${KEEP_ALIVE}\"
}" >/dev/null
echo "    Embedding model loaded."

echo "3/3 Pre-warming text model (${OLLAMA_TEXT_MODEL}, keep_alive ${KEEP_ALIVE})..."
docker compose exec -T ollama curl -sf http://localhost:11434/api/generate -d "{
  \"model\": \"${OLLAMA_TEXT_MODEL}\",
  \"prompt\": \"Sag kurz Hallo auf Deutsch.\",
  \"keep_alive\": \"${KEEP_ALIVE}\",
  \"stream\": false
}" >/dev/null
echo "    Text model loaded."

echo "All 3 models pre-warmed with ${KEEP_ALIVE} keep-alive."
