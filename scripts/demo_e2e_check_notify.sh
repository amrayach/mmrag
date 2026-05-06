#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT}/data/eval/demo_health"
LOG_FILE="${LOG_DIR}/notifications.log"

# TODO: Replace this stub only after the health check has been observed stable.
# Real notifier options to consider:
# - local email via mail/sendmail for on-host operator alerts;
# - ntfy.sh for lightweight push notifications;
# - generic webhook for existing monitoring systems;
# - Slack/Teams webhook if the demo ops channel standardizes on one.
# This session intentionally performs no external network calls.

mkdir -p "${LOG_DIR}"
{
  printf '[%s] demo_e2e_check_notify stub invoked' "$(date -Is)"
  if [[ $# -gt 0 ]]; then
    printf ' args='
    printf '%q ' "$@"
  fi
  printf '\n'
} >> "${LOG_FILE}"

exit 0
