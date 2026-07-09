#!/usr/bin/env bash
# Análisis de lookahead bias (informative pairs BTC 1h/4h).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STRATEGY="${1:-SmokeTestStrategy}"
TIMERANGE="${TIMERANGE:-20240101-20240201}"

echo "==> Lookahead analysis: ${STRATEGY} (${TIMERANGE})"

docker compose run --rm freqtrade lookahead-analysis \
  --config user_data/config/base.json \
  --config user_data/config/backtest.json \
  --strategy "${STRATEGY}" \
  --config user_data/config/lookahead.json \
  --strategy-path user_data/strategies \
  --timerange "${TIMERANGE}"

echo "==> Revisar salida: no debe haber indicadores con lookahead detectado."
