#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

KEEP_ALIVE="1h"

# Use host curl → Ollama via internal Docker network
# Find Ollama's container IP for direct access
OLLAMA_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ammer_mmragv2_ollama)
OLLAMA_URL="http://${OLLAMA_IP}:11434"

echo "1/3 Pre-warming embedding model (${OLLAMA_EMBED_MODEL}, keep_alive ${KEEP_ALIVE})..."
curl -sf "${OLLAMA_URL}/api/embeddings" -d "{
  \"model\": \"${OLLAMA_EMBED_MODEL}\",
  \"prompt\": \"test\",
  \"keep_alive\": \"${KEEP_ALIVE}\"
}" >/dev/null
echo "    Embedding model loaded."

echo "2/3 Pre-warming text model (${OLLAMA_TEXT_MODEL}, keep_alive ${KEEP_ALIVE})..."
curl -sf "${OLLAMA_URL}/api/generate" -d "{
  \"model\": \"${OLLAMA_TEXT_MODEL}\",
  \"prompt\": \"Sag kurz Hallo.\",
  \"keep_alive\": \"${KEEP_ALIVE}\",
  \"stream\": false,
  \"options\": {\"num_ctx\": 4096}
}" >/dev/null
echo "    Text model loaded."

echo "3/3 Pre-warming vision model (${OLLAMA_VISION_MODEL}, keep_alive ${KEEP_ALIVE})..."
curl -sf "${OLLAMA_URL}/api/chat" -d "{
  \"model\": \"${OLLAMA_VISION_MODEL}\",
  \"messages\": [{\"role\": \"user\", \"content\": \"Say hello.\"}],
  \"keep_alive\": \"${KEEP_ALIVE}\",
  \"stream\": false,
  \"options\": {\"num_ctx\": 4096}
}" >/dev/null
echo "    Vision model loaded."

echo "All 3 models pre-warmed with ${KEEP_ALIVE} keep-alive."
