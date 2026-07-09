#!/usr/bin/env bash
# Descarga datos históricos para backtesting (solo user_data/data — reales).
# Por defecto: --erase. PREPEND=1 para extender sin borrar.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TIMERANGE="${TIMERANGE:-20210101-}"
TIMEFRAMES="${TIMEFRAMES:-1h 15m 4h}"
PAIRS="${PAIRS:-BTC/USDT ETH/USDT BNB/USDT SOL/USDT XRP/USDT}"
ERASE_FLAG=()
if [[ "${PREPEND:-0}" != "1" ]]; then
  ERASE_FLAG=(--erase)
fi

echo "==> Descargando datos Binance spot (user_data/data — solo reales)"
echo "    Timerange: ${TIMERANGE}"
echo "    Timeframes: ${TIMEFRAMES}"
echo "    Pares: ${PAIRS}"
if [[ ${#ERASE_FLAG[@]} -gt 0 ]]; then
  echo "    Modo: --erase (descarga limpia)"
fi

docker compose run --rm freqtrade download-data \
  --config user_data/config/base.json \
  --config user_data/config/backtest.json \
  --exchange binance \
  --timerange "${TIMERANGE}" \
  --timeframes ${TIMEFRAMES} \
  --pairs ${PAIRS} \
  "${ERASE_FLAG[@]}"

echo "==> Descarga completada en user_data/data/ (separado de tests/fixtures/data/)"
