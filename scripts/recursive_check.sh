#!/usr/bin/env bash
# Recursive analysis — estabilidad de indicadores vs warmup.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STRATEGY="${1:-SmokeTestStrategy}"
TIMERANGE="${TIMERANGE:-20240101-20240320}"
STARTUP_CANDLES="${STARTUP_CANDLES:-199 499 999 1999}"

echo "==> Recursive analysis: ${STRATEGY} (${TIMERANGE})"

docker compose run --rm freqtrade recursive-analysis \
  --config user_data/config/base.json \
  --config user_data/config/backtest.json \
  --strategy "${STRATEGY}" \
  --strategy-path user_data/strategies \
  --timerange "${TIMERANGE}" \
  --startup-candle ${STARTUP_CANDLES}

echo "==> Revisar tabla: variación <0.1% en columna del startup_candle_count de la estrategia."
