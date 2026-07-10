#!/usr/bin/env bash
# Screen pre-validación (Unix)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STRATEGY="${1:?strategy name}"
TIMERANGE="${2:-20210101-}"
EXTRA=()
if [[ "${FIXTURES:-}" == "1" ]]; then
  EXTRA+=(--fixtures)
fi

python user_data/tools/screen_strategy.py "$STRATEGY" --timerange "$TIMERANGE" "${EXTRA[@]}"
