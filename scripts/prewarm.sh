#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

KEEP_ALIVE="1h"
REQUIRED_MODELS=("${OLLAMA_EMBED_MODEL}" "${OLLAMA_TEXT_MODEL}" "${OLLAMA_VISION_MODEL}")

# Use host curl → Ollama via internal Docker network
# Find Ollama's container IP for direct access
OLLAMA_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ammer_mmragv2_ollama)
OLLAMA_URL="http://${OLLAMA_IP}:11434"

assert_gpu_residency() {
  local ps_json
  ps_json=$(curl -sf "${OLLAMA_URL}/api/ps")

  PS_JSON="$ps_json" python3 - "${REQUIRED_MODELS[@]}" <<'PY'
import json
import os
import sys

required = sys.argv[1:]
data = json.loads(os.environ["PS_JSON"])
models = data.get("models", [])

def aliases(name: str) -> set[str]:
    if ":" in name:
        return {name}
    return {name, f"{name}:latest"}

loaded = {}
for model in models:
    names = {model.get("name", ""), model.get("model", "")}
    for required_name in required:
        if names & aliases(required_name):
            loaded[required_name] = model

errors = []
for required_name in required:
    model = loaded.get(required_name)
    if not model:
        errors.append(f"{required_name}: not resident after prewarm")
        continue
    if int(model.get("size_vram") or 0) <= 0:
        errors.append(f"{required_name}: resident but size_vram=0 (CPU fallback)")

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    print("Loaded models:", file=sys.stderr)
    for model in models:
        size_gib = int(model.get("size", 0)) / (1024 ** 3)
        vram_gib = int(model.get("size_vram") or 0) / (1024 ** 3)
        print(
            f"  {model.get('name')} size={size_gib:.1f} GiB "
            f"vram={vram_gib:.1f} GiB context={model.get('context_length')}",
            file=sys.stderr,
        )
    sys.exit(1)

print("GPU residency verified:")
for required_name in required:
    model = loaded[required_name]
    size_gib = int(model.get("size", 0)) / (1024 ** 3)
    vram_gib = int(model.get("size_vram") or 0) / (1024 ** 3)
    print(f"  {model.get('name')}: size={size_gib:.1f} GiB, vram={vram_gib:.1f} GiB")
PY
}

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

echo "Verifying all required models are resident on GPU..."
assert_gpu_residency

echo "All 3 models pre-warmed on GPU with ${KEEP_ALIVE} keep-alive."
