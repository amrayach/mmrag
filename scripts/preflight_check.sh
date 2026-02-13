#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

ports=(56150 56151 56152 56153 56154 56157)
echo "== Preflight: checking ports =="
for p in "${ports[@]}"; do
  if ss -tuln | grep -q ":$p "; then
    echo "ERROR: Port $p is already in use."
    exit 1
  fi
done
echo "OK: ports are free."

echo "== Preflight: docker access =="
docker ps >/dev/null
echo "OK: docker works."

echo "== Preflight: volume collision (FAIL by default) =="
if docker volume ls | awk '{print $2}' | grep -qE '^ammer-mmragv2_'; then
  echo "ERROR: Volumes from previous deployment exist."
  echo "If you want a clean redeploy: run 'docker compose down -v' inside the project root (MANUAL)."
  exit 1
fi
echo "OK: no conflicting volumes."

echo "== Preflight: tailscale serve status (informational) =="
tailscale serve status || true

echo "Preflight checks passed."
