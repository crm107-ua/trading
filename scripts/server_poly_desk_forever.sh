#!/usr/bin/env bash
# PM2 entry — desk REAL infinito + informes email cada 3h.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

# Evitar CRLF de Windows al sourcer .env
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' "$ROOT/.env")
  set +a
fi

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi

mkdir -p "$ROOT/user_data/logs" "$ROOT/polymarket/data_local/local_lab"

exec "$PY" -m polymarket.research.local_lab.desk_forever \
  --minutes "${POLY_DESK_MINUTES:-12}" \
  --capital "${POLY_DESK_CAPITAL:-5}" \
  --config "${POLY_DESK_CONFIG:-maker_demo_promo_pulse_micro5_scalp.json}" \
  --pause-s "${POLY_DESK_PAUSE_S:-45}" \
  --min-balance "${POLY_DESK_MIN_BALANCE:-5}" \
  --email-every-s "${POLY_DESK_EMAIL_EVERY_S:-10800}"
