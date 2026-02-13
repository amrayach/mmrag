#!/usr/bin/env bash
set -euo pipefail
echo "== Tailscale Serve status BEFORE changes =="
tailscale serve status || true
echo ""
echo "If 8450-8454 already appear above, STOP and resolve conflicts manually."
