#!/usr/bin/env bash
# Third research process: periodic digest + improvement scan (WATCH_ONLY).
# Does NOT place orders. Safe alongside private_manager + progress_watch.
set -euo pipefail
ROOT="${ROOT:-/var/www/html/trader}"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

RUN="$ROOT/polymarket/data_local/local_lab/vps_runs"
mkdir -p "$RUN/telemetry"
INTERVAL_SEC="${RESEARCH_IMPROVE_INTERVAL_SEC:-1800}"
DIGEST_EVERY="${RESEARCH_DIGEST_EVERY:-6}"  # every N loops (~3h if 1800s)
loop=0

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] RESEARCH_IMPROVE ON | digest+scan | interval=${INTERVAL_SEC}s | NO posts" | tee -a "$RUN/ALERTS.log"

while true; do
  loop=$((loop + 1))
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[$ts] improve_loop=$loop" | tee -a "$RUN/research_improve.log"

  # Improvement candidates from telemetry (may be empty early)
  "$ROOT/.venv/bin/python" -u "$ROOT/polymarket/scripts/research_improvement_scanner.py" \
    >>"$RUN/research_improve.log" 2>&1 || true

  # Evidence progress refresh
  "$ROOT/.venv/bin/python" -u -m polymarket.research.local_lab.research_telemetry \
    >>"$RUN/research_improve.log" 2>&1 || \
  "$ROOT/.venv/bin/python" -u -c "
from polymarket.research.local_lab.research_telemetry import write_evidence_progress
import json
print(json.dumps(write_evidence_progress(), indent=2))
" >>"$RUN/research_improve.log" 2>&1 || true

  # Digest every N loops; Telegram only on digest ticks
  if (( loop % DIGEST_EVERY == 0 )); then
    "$ROOT/.venv/bin/python" -u -m polymarket.research.local_lab.research_daily_digest --hours 24 --telegram \
      >>"$RUN/research_improve.log" 2>&1 || true
  else
    "$ROOT/.venv/bin/python" -u -m polymarket.research.local_lab.research_daily_digest --hours 6 \
      >>"$RUN/research_improve.log" 2>&1 || true
  fi

  sleep "$INTERVAL_SEC"
done
