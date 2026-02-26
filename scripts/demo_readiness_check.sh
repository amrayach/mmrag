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
if [ "$RUNNING" -eq 10 ]; then
  pass "All 10 containers running"
else
  fail "$RUNNING/10 containers running"
  docker compose -p ammer-mmragv2 ps --format "table {{.Name}}\t{{.State}}" 2>/dev/null
fi

# ── 2. Ollama responds + models loaded ────────────────────────────────────
echo "== 2. Ollama models =="
if MODELS=$(docker compose -p ammer-mmragv2 exec -T ollama ollama list 2>/dev/null); then
  for m in "${OLLAMA_TEXT_MODEL}" "nomic-embed-text" "qwen2.5vl:7b"; do
    if echo "$MODELS" | grep -q "$m"; then
      pass "Model $m present"
    else
      fail "Model $m missing"
    fi
  done
else
  fail "Ollama not responding"
fi

# ── 3. n8n webhooks (both workflows active) ───────────────────────────────
echo "== 3. n8n webhooks =="
CHAT_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:56150/webhook/rag-chat \
  -H "Content-Type: application/json" -d '{"messages":[]}' 2>/dev/null || echo "000")
if [ "$CHAT_CODE" != "404" ] && [ "$CHAT_CODE" != "000" ]; then
  pass "Chat Brain webhook reachable (HTTP $CHAT_CODE)"
else
  fail "Chat Brain webhook not found (HTTP $CHAT_CODE)"
fi

INGEST_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:56150/webhook/ingest-now 2>/dev/null || echo "000")
if [ "$INGEST_CODE" != "404" ] && [ "$INGEST_CODE" != "000" ]; then
  pass "Ingestion Factory webhook reachable (HTTP $INGEST_CODE)"
else
  fail "Ingestion Factory webhook not found (HTTP $INGEST_CODE)"
fi

RSS_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:56150/webhook/rss-ingest-now 2>/dev/null || echo "000")
if [ "$RSS_CODE" != "404" ] && [ "$RSS_CODE" != "000" ]; then
  pass "RSS Ingestion webhook reachable (HTTP $RSS_CODE)"
else
  warn "RSS Ingestion webhook not found (HTTP $RSS_CODE) — import workflow 03"
fi

# ── 4. Chat returns non-500 (proves Ollama reachable from n8n) ────────────
echo "== 4. Chat pipeline (end-to-end) =="
CHAT_RESP=$(curl -s -m 120 -X POST http://127.0.0.1:56150/webhook/rag-chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Antworte nur mit OK."}]}' 2>/dev/null)
if echo "$CHAT_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('answer')" 2>/dev/null; then
  pass "Chat returned a valid answer"
else
  HTTP_ERR=$(echo "$CHAT_RESP" | head -c 200)
  fail "Chat did not return a valid answer: $HTTP_ERR"
fi

# ── 5. Tailscale serve rules ─────────────────────────────────────────────
echo "== 5. Tailscale serve =="
SERVE_OUT=$(tailscale serve status 2>&1 || true)
if echo "$SERVE_OUT" | grep -q "$TAILNET_HOST"; then
  pass "Tailscale serve rules active"
else
  fail "Tailscale serve rules not found"
fi

# ── 6. Tailnet URLs respond ──────────────────────────────────────────────
echo "== 6. Tailnet URLs =="
for port in 8450 8451 8452 8453 8454; do
  CODE=$(curl -k -s -o /dev/null -w "%{http_code}" -m 10 "https://${TAILNET_HOST}:${port}" 2>/dev/null || echo "000")
  if [ "$CODE" != "000" ]; then
    pass "https://${TAILNET_HOST}:${port} -> HTTP $CODE"
  else
    fail "https://${TAILNET_HOST}:${port} -> unreachable"
  fi
done

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
