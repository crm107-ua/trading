#!/usr/bin/env bash
# Paper maker v7 lock — batch real-feed en servidor (PM2).
# Arrancar SIN tocar otros procesos:
#   cd /var/www/html/trader
#   pm2 start scripts/ecosystem.poly_paper_v7.config.cjs
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

mkdir -p "$ROOT/polymarket/data_local/local_lab" "$ROOT/user_data/logs"
LOG="$ROOT/polymarket/data_local/local_lab/hito_v7_lock.log"

echo "[$(date -Iseconds)] START poly-paper-v7 sessions=6 minutes=10 -> $LOG"
# Unbuffered + append al log del monitor; PM2 también guarda out/err
python3 -u -m polymarket.research.local_lab.batch_paper_eval \
  --strategy maker_edge \
  --config polymarket/config/maker_demo_100_usd_margin_v7_lock.json \
  --sessions 6 \
  --minutes 10 \
  --target 0.5 \
  >>"$LOG" 2>&1
ec=$?
echo "[$(date -Iseconds)] END poly-paper-v7 exit=$ec"
exit "$ec"
