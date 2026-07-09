#!/usr/bin/env bash
# Signal truncation check — guard principal anti-lookahead en señales.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STRATEGY="${1:-SmokeTestStrategy}"
TIMERANGE="${TIMERANGE:-20240101-20240320}"

docker compose run --rm freqtrade python user_data/tools/signal_truncation_check.py \
  --strategy "${STRATEGY}" \
  --timerange "${TIMERANGE}"
