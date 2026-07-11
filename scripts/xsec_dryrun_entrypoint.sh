#!/bin/sh
set -e
# Params congelados m35 — no compartir estado con screen/hyperopt.
cp /freqtrade/user_data/strategies/XSecMomentum_m35_frozen.json \
  /freqtrade/user_data/strategies/XSecMomentum.json
exec freqtrade "$@"
