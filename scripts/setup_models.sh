#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

echo "Waiting for Ollama daemon to be ready..."
until docker compose exec -T ollama ollama list >/dev/null 2>&1; do
  sleep 2
done
echo "Ollama is ready."

echo "Pulling models once into persistent volume..."
docker compose exec -T ollama ollama pull "${OLLAMA_TEXT_MODEL}"
docker compose exec -T ollama ollama pull "${OLLAMA_VISION_MODEL}"
docker compose exec -T ollama ollama pull "${OLLAMA_EMBED_MODEL}"
echo "Models pulled and cached."
