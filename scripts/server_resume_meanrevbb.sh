#!/usr/bin/env bash
# Reanudar validación MeanRevBB en servidor (PM2).
set -euo pipefail
ROOT="/var/www/html/trader"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore::FutureWarning}"
PY="${ROOT}/.venv/bin/python"
WATCH="${ROOT}/scripts/watch_validation_progress.sh"

export HYPEROPT_JOB_WORKERS="${HYPEROPT_JOB_WORKERS:-1}"
RUN_ID="${VALIDATION_RUN_ID:-20260709_162954}"

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: carlos sin acceso a Docker. Ejecutar una vez como root:"
  echo "  sudo usermod -aG docker carlos"
  echo "  # cerrar sesión SSH y volver a entrar"
  exit 1
fi

"$PY" -m pipeline.run_lock check
if [[ $? -eq 3 ]]; then
  echo "Lock activo — otro run en curso"
  exit 3
fi

if [[ -x "$WATCH" ]]; then
  nohup "$WATCH" >/dev/null 2>&1 &
fi

exec "$PY" -W ignore::FutureWarning -m pipeline.run_validation MeanRevBB \
  --profile full \
  --resume-run-id "$RUN_ID"
