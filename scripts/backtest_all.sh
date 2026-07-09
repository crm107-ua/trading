#!/usr/bin/env bash
# Pipeline de validación antes de backtest.
# REAL_DATA=1 → user_data/data (reales). Por defecto → fixtures para estrategias cuant.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STRATEGY="${1:-SmokeTestStrategy}"
FIXTURE_STRATEGIES="SmokeTestStrategy TrendRider MeanRevBB BreakoutVol RegimeSwitcher GridDCA"
CONFIG_ARGS=(--config user_data/config/base.json --config user_data/config/backtest.json)
DATADIR_ARGS=()

if [[ "${REAL_DATA:-0}" == "1" ]]; then
  TIMERANGE="${TIMERANGE:-20230101-20240320}"
  RECURSIVE_RANGE="${RECURSIVE_RANGE:-20230101-20240320}"
  echo "==> Modo datos REALES (user_data/data)"
else
  TIMERANGE="${TIMERANGE:-20240101-20240320}"
  RECURSIVE_RANGE="${RECURSIVE_RANGE:-20240101-20240320}"
  DATADIR_ARGS=(--datadir /freqtrade/user_data/fixtures/data/binance)
  if echo "$FIXTURE_STRATEGIES" | grep -qw "$STRATEGY"; then
    CONFIG_ARGS+=(--config user_data/config/backtest_fixtures.json)
  fi
  echo "==> Modo FIXTURES (user_data/fixtures/data)"
fi

STARTUP_CANDLES="${STARTUP_CANDLES:-199 499 999 1999}"

echo "==> Regime variety check: ${STRATEGY} (${TIMERANGE})"
docker compose run --rm --entrypoint python freqtrade user_data/tools/regime_variety_check.py \
  --strategy "${STRATEGY}" \
  --timerange "${TIMERANGE}" \
  "${CONFIG_ARGS[@]}"

echo "==> Signal truncation check: ${STRATEGY} (${TIMERANGE})"
docker compose run --rm --entrypoint python freqtrade user_data/tools/signal_truncation_check.py \
  --strategy "${STRATEGY}" \
  --timerange "${TIMERANGE}" \
  "${CONFIG_ARGS[@]}"

echo "==> Recursive analysis: ${STRATEGY} (${RECURSIVE_RANGE})"
# shellcheck disable=SC2086
docker compose run --rm freqtrade recursive-analysis \
  "${CONFIG_ARGS[@]}" \
  "${DATADIR_ARGS[@]}" \
  --strategy "${STRATEGY}" \
  --strategy-path user_data/strategies \
  --timerange "${RECURSIVE_RANGE}" \
  --startup-candle ${STARTUP_CANDLES}

echo "==> Lookahead trade-based (advisory): ${STRATEGY} (${TIMERANGE})"
docker compose run --rm freqtrade lookahead-analysis \
  "${CONFIG_ARGS[@]}" \
  "${DATADIR_ARGS[@]}" \
  --config user_data/config/lookahead.json \
  --strategy "${STRATEGY}" \
  --strategy-path user_data/strategies \
  --timerange "${TIMERANGE}" || true
echo "    (advisory — ver docs/OPERATIONS.md)"

if [[ "${STRATEGY}" == "GridDCA" && "${REAL_DATA:-0}" != "1" ]]; then
  echo "==> GridDCA cycle check (fixtures)"
  docker compose run --rm --entrypoint python freqtrade user_data/tools/grid_dca_check.py \
    --strategy GridDCAFixture \
    --timerange 20240120-20240128 \
    --min-position-adjustments 3 \
    --require-stop-after-dca \
    --pairs BTC/USDT \
    "${CONFIG_ARGS[@]}"
fi

echo "==> Backtest: ${STRATEGY} (${TIMERANGE})"
docker compose run --rm freqtrade backtesting \
  "${CONFIG_ARGS[@]}" \
  "${DATADIR_ARGS[@]}" \
  --strategy "${STRATEGY}" \
  --timerange "${TIMERANGE}" \
  --cache none \
  --breakdown month

echo "==> Pipeline completado para ${STRATEGY}"
