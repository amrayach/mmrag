#!/usr/bin/env bash
# Demo readiness smoke test — validates the full MMRAG pipeline is functional
# before asking external users to test via Tailscale.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found."
  exit 1
fi
set -a; source .env; set +a

PASS=0
FAIL=0
WARN=0

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }
warn() { echo "  WARN: $1"; WARN=$((WARN + 1)); }

TAILNET_HOST="spark-e010.tail907fce.ts.net"

# ── 1. Containers (expect 10) ─────────────────────────────────────────────
echo "== 1. Docker containers =="
RUNNING=$(docker compose -p ammer-mmragv2 ps --status running --format '{{.Name}}' 2>/dev/null | wc -l)
if [ "$RUNNING" -ge 10 ]; then
  pass "All 10 containers running"
else
  fail "$RUNNING/10 containers running"
  docker compose -p ammer-mmragv2 ps --format "table {{.Name}}\t{{.State}}" 2>/dev/null
fi

# ── 2. Ollama responds + models loaded ────────────────────────────────────
echo "== 2. Ollama models =="
if MODELS=$(docker compose -p ammer-mmragv2 exec -T ollama ollama list 2>/dev/null); then
  for m in "${OLLAMA_TEXT_MODEL}" "bge-m3" "qwen2.5vl:7b"; do
    if echo "$MODELS" | grep -q "$m"; then
      pass "Model $m present"
    else
      fail "Model $m missing"
    fi
  done
else
  fail "Ollama not responding"
fi

# ── 2b. Ollama GPU residency ─────────────────────────────────────────────
echo "== 2b. Ollama GPU residency =="
OLLAMA_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ammer_mmragv2_ollama 2>/dev/null || true)
if [ -n "$OLLAMA_IP" ] && PS_JSON=$(curl -sf "http://${OLLAMA_IP}:11434/api/ps" 2>/dev/null); then
  if GPU_STATUS=$(PS_JSON="$PS_JSON" python3 - "${OLLAMA_EMBED_MODEL}" "${OLLAMA_TEXT_MODEL}" "${OLLAMA_VISION_MODEL}" <<'PY'
import json
import os
import sys

required = sys.argv[1:]
models = json.loads(os.environ["PS_JSON"]).get("models", [])

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
details = []
for required_name in required:
    model = loaded.get(required_name)
    if not model:
        errors.append(f"{required_name}: missing")
        continue
    size_vram = int(model.get("size_vram") or 0)
    details.append(f"{model.get('name')} vram={size_vram / (1024 ** 3):.1f}GiB")
    if size_vram <= 0:
        errors.append(f"{required_name}: CPU fallback")

if errors:
    print("; ".join(errors))
    if details:
        print("Loaded: " + "; ".join(details))
    sys.exit(1)

print("; ".join(details))
PY
  ); then
    pass "Required models resident on GPU: $GPU_STATUS"
  else
    fail "Required models are not all on GPU: $GPU_STATUS"
  fi
else
  fail "Could not query Ollama /api/ps for GPU residency"
fi

# ── 3. n8n webhooks (ingestion readiness) ─────────────────────────────────
# n8n is optional for chat since CONTEXT_MODE=direct.
# These checks verify ingestion workflow readiness only.
echo "== 3. n8n webhooks (ingestion — optional for chat) =="
CHAT_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:56150/webhook/rag-chat \
  -H "Content-Type: application/json" -d '{"messages":[]}' 2>/dev/null || echo "000")
if [ "$CHAT_CODE" != "404" ] && [ "$CHAT_CODE" != "000" ]; then
  pass "Chat Brain webhook reachable (HTTP $CHAT_CODE)"
else
  warn "Chat Brain webhook not found (HTTP $CHAT_CODE) — not needed for chat (direct mode)"
fi

INGEST_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:56150/webhook/ingest-now 2>/dev/null || echo "000")
if [ "$INGEST_CODE" != "404" ] && [ "$INGEST_CODE" != "000" ]; then
  pass "Ingestion Factory webhook reachable (HTTP $INGEST_CODE)"
else
  warn "Ingestion Factory webhook not found (HTTP $INGEST_CODE) — ingestion won't auto-trigger"
fi

RSS_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:56150/webhook/rss-ingest-now 2>/dev/null || echo "000")
if [ "$RSS_CODE" != "404" ] && [ "$RSS_CODE" != "000" ]; then
  pass "RSS Ingestion webhook reachable (HTTP $RSS_CODE)"
else
  warn "RSS Ingestion webhook not found (HTTP $RSS_CODE) — import workflow 03"
fi

# ── 4. n8n context pipeline (optional — direct mode bypasses this) ────────
# n8n is optional for chat since CONTEXT_MODE=direct.
echo "== 4. n8n context pipeline (optional) =="
CHAT_RESP=$(curl -s -m 120 -X POST http://127.0.0.1:56150/webhook/rag-chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Antworte nur mit OK."}]}' 2>/dev/null)
if echo "$CHAT_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('chatRequestBody')" 2>/dev/null; then
  pass "n8n returned context with chatRequestBody"
else
  HTTP_ERR=$(echo "$CHAT_RESP" | head -c 200)
  warn "n8n did not return valid context (chat works without it): $HTTP_ERR"
fi

# ── 5. RAG Gateway SSE streaming ────────────────────────────────────────
echo "== 5. RAG Gateway streaming =="
SSE_RESP=$(timeout 90 curl -s -N -X POST http://127.0.0.1:56155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Antworte nur mit OK."}],"stream":true}' 2>/dev/null || true)
if echo "$SSE_RESP" | grep -q "^data:"; then
  pass "SSE streaming chunks received from rag-gateway"
else
  fail "No SSE chunks from rag-gateway: $(echo "$SSE_RESP" | head -c 100)"
fi

# ── 5b. End-to-end streaming test (full chain) ────────────────────────
echo "== 5b. End-to-end pipeline (rag-gateway → Ollama → stream) =="
E2E_RESP=$(curl -s -m 120 -N -X POST http://127.0.0.1:56155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Was ist ein Vektor? Antworte in einem Satz."}],"stream":true}' 2>/dev/null || true)
# Extract data: lines that contain actual content (delta with text), skip [DONE] and empty data
E2E_CONTENT=$(echo "$E2E_RESP" | grep '^data:' | grep -v '\[DONE\]' | grep '"content"' | head -1 || true)
if [ -n "$E2E_CONTENT" ]; then
  pass "End-to-end SSE chunk with content received"
else
  # Check if we got any data: lines at all
  E2E_ANY=$(echo "$E2E_RESP" | grep -c '^data:' || true)
  if [ "$E2E_ANY" -gt 1 ]; then
    pass "End-to-end SSE streaming works ($E2E_ANY data chunks)"
  else
    fail "End-to-end streaming failed — no content chunks (got ${E2E_ANY:-0} data lines)"
  fi
fi

# ── 6. Demo mode check (rss-ingest stopped) ───────────────────────────
echo "== 6. Demo mode (rss-ingest) =="
RSS_STATE=$(docker compose -p ammer-mmragv2 ps --format '{{.State}}' rss-ingest 2>/dev/null || echo "unknown")
if echo "$RSS_STATE" | grep -qi "running"; then
  warn "rss-ingest is running (GPU contention possible during demo — run 'make demo-start')"
else
  pass "rss-ingest is stopped (demo mode active, GPU freed)"
fi

# ── 7. Tailscale serve rules ─────────────────────────────────────────────
echo "== 5. Tailscale serve =="
SERVE_OUT=$(tailscale serve status 2>&1 || true)
if echo "$SERVE_OUT" | grep -q "$TAILNET_HOST"; then
  pass "Tailscale serve rules active"
else
  fail "Tailscale serve rules not found"
fi
if [ "${DEMO_SITE_OPENWEBUI_ENABLED:-false}" = "true" ] && echo "$SERVE_OUT" | grep -q "${TAILNET_HOST}:8451"; then
  warn "Direct OpenWebUI Serve is active during hybrid mode; keep it internal/admin-only because it bypasses demo-site gate"
fi

# ── 8. Tailnet URLs respond ──────────────────────────────────────────────
echo "== 8. Tailnet URLs =="
for port in 8450 8451 8452 8453 8454; do
  CODE=$(curl -k -s -o /dev/null -w "%{http_code}" -m 10 "https://${TAILNET_HOST}:${port}" 2>/dev/null || echo "000")
  if [ "$CODE" != "000" ]; then
    pass "https://${TAILNET_HOST}:${port} -> HTTP $CODE"
  else
    fail "https://${TAILNET_HOST}:${port} -> unreachable"
  fi
done

# ── 16. opendataloader integration ───────────────────────────────────────
echo "== 16. opendataloader integration =="
if docker compose -p ammer-mmragv2 exec -T pdf-ingest java -version >/dev/null 2>&1; then
  pass "Java runtime present in pdf-ingest"
else
  fail "Java runtime not available in pdf-ingest"
fi
BBOX_COUNT=$(docker compose -p ammer-mmragv2 exec -T \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  psql -h 127.0.0.1 -U "${POSTGRES_USER}" -d "${RAG_DB}" -At \
  -c "SELECT count(*) FROM rag_chunks WHERE meta ? 'bbox';" 2>/dev/null || echo "0")
if [ "${BBOX_COUNT:-0}" -gt 0 ]; then
  pass "$BBOX_COUNT chunks carry meta.bbox"
else
  fail "no chunks carry meta.bbox — pipeline did not produce structure metadata"
fi

# ── Summary ──────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  PASS: $PASS  |  FAIL: $FAIL  |  WARN: $WARN"
echo "========================================"
if [ "$FAIL" -gt 0 ]; then
  echo "Demo is NOT ready. Fix failures above."
  exit 1
else
  echo "Demo is ready for external testing."
  exit 0
fi
