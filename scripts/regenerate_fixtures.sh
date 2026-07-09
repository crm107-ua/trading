#!/usr/bin/env bash
# Regenera fixtures sintéticos (BULL + RANGE) vía Docker.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Regenerando fixtures (BULL + RANGE)"
docker compose run --rm --entrypoint "python" \
  -v "${ROOT}:/work" \
  -w /work \
  freqtrade tests/fixtures/generate_data.py

echo "==> Fixtures en tests/fixtures/data/binance/"