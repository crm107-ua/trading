#!/usr/bin/env bash
# Forward resolve loop: snapshots → cases when markets close (WATCH_ONLY).
set -euo pipefail
ROOT="${ROOT:-/var/www/html/trader}"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
RUN="$ROOT/polymarket/data_local/local_lab/vps_runs"
mkdir -p "$RUN/telemetry"
INTERVAL_SEC="${FORWARD_RESOLVE_INTERVAL_SEC:-600}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FORWARD_RESOLVE ON | interval=${INTERVAL_SEC}s | NO posts" | tee -a "$RUN/ALERTS.log"

while true; do
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[$ts] resolve_tick" | tee -a "$RUN/forward_resolve.log"
  "$ROOT/.venv/bin/python" -u -m polymarket.research.local_lab.resolve_forward_cases \
    >>"$RUN/forward_resolve.log" 2>&1 || true
  "$ROOT/.venv/bin/python" -u -m polymarket.research.local_lab.research_telemetry \
    >>"$RUN/forward_resolve.log" 2>&1 || true
  sleep "$INTERVAL_SEC"
done
