#!/usr/bin/env bash
# Escribe progreso % en logs PM2 (sin ruido de warnings).
set -euo pipefail
ROOT="/var/www/html/trader"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export PYTHONWARNINGS="ignore::FutureWarning"
PY="${ROOT}/.venv/bin/python"
INTERVAL="${VALIDATION_PROGRESS_INTERVAL:-120}"
OUT_LOG="${ROOT}/user_data/logs/pm2_meanrevbb.out.log"
STRATEGY="${VALIDATION_STRATEGY:-MeanRevBB}"
RUN_ID="${VALIDATION_RUN_ID:-20260709_162954}"

_ts() {
  date "+%Y-%m-%dT%H:%M:%S"
}

while true; do
  if ! pm2 pid meanrevbb-validation >/dev/null 2>&1; then
    line="$(_ts) PROGRESO — meanrevbb-validation no está en PM2"
    echo "$line" >>"$OUT_LOG"
    exit 0
  fi
  line="$(_ts) $("$PY" "${ROOT}/scripts/validation_progress.py" \
    --strategy "$STRATEGY" --run-id "$RUN_ID" --format compact 2>/dev/null \
    || echo "PROGRESO — error calculando progreso")"
  echo "$line" >>"$OUT_LOG"
  sleep "$INTERVAL"
done
