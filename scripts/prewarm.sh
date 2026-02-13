#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

echo "Pre-warming text model (keep_alive 1h)..."
docker compose exec -T rag-gateway curl -s http://ollama:11434/api/generate -d "{
  \"model\": \"${OLLAMA_TEXT_MODEL}\",
  \"prompt\": \"Sag kurz Hallo auf Deutsch.\",
  \"keep_alive\": \"1h\",
  \"stream\": false
}" >/dev/null
echo "Prewarm complete."
