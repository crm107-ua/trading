#!/usr/bin/env bash
# Overnight autonomous paper autotune + email reports (PM2).
#   pm2 start scripts/ecosystem.poly_overnight.config.cjs
set -euo pipefail
ROOT="/var/www/html/trader"
cd "$ROOT"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export PYTHONUNBUFFERED=1
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
export POLY_DISABLE_AUTONOMOUS_OOS=1
export BATCH_STOP_AFTER_LOSS_STREAK="${BATCH_STOP_AFTER_LOSS_STREAK:-2}"
export NVIDIA_NIM_MODE="${NVIDIA_NIM_MODE:-hybrid}"
export NVIDIA_NIM_PROFIT_ASSIST="${NVIDIA_NIM_PROFIT_ASSIST:-1}"
export NVIDIA_NIM_STRONG_EDGE_MULT="${NVIDIA_NIM_STRONG_EDGE_MULT:-2.0}"
export NVIDIA_NIM_EXIT_EVERY_S="${NVIDIA_NIM_EXIT_EVERY_S:-2}"
export OVERNIGHT_MAX_TRIALS="${OVERNIGHT_MAX_TRIALS:-12}"
export OVERNIGHT_HIT_WR="${OVERNIGHT_HIT_WR:-0.5}"
export OVERNIGHT_HIT_AVG="${OVERNIGHT_HIT_AVG:-8}"
export OVERNIGHT_HIT_TOTAL="${OVERNIGHT_HIT_TOTAL:-40}"
export MAIL_TO="${MAIL_TO:-caromamusic@gmail.com}"

mkdir -p "$ROOT/polymarket/data_local/local_lab/overnight" "$ROOT/user_data/logs"
LOG="$ROOT/polymarket/data_local/local_lab/overnight/pm2_overnight_driver.log"

echo "[$(date -Iseconds)] START poly-overnight -> $LOG"
python3 -u -m polymarket.research.local_lab.overnight_autotune >>"$LOG" 2>&1
ec=$?
echo "[$(date -Iseconds)] END poly-overnight exit=$ec" | tee -a "$LOG"
exit "$ec"
