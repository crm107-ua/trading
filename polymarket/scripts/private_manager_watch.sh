#!/usr/bin/env bash
# Watch-only private manager — DNA vigilante, NO auto-execute, NO arm real.
# Alerta EDGE por Telegram; el operador decide. RESEARCH_ONLY posture.
set -u
cd /var/www/html/trader
source .venv/bin/activate
export PYTHONPATH=/var/www/html/trader
# Force SAFE — never arm from this script
export POLY_LIVE_ARMED=0
export POLY_LIVE_DRY_RUN=1
# Do NOT set POLY_LADDER_REAL_CONFIRM here (blocks accidental execute)
unset POLY_LADDER_REAL_CONFIRM || true
export POLY_LADDER_WATCH_ONLY=1

LOG_DIR=polymarket/data_local/local_lab/vps_runs
mkdir -p "$LOG_DIR"
DAY=$(date -u +%Y%m%d)
LOG="$LOG_DIR/private_manager_${DAY}.log"
ALERTS="$LOG_DIR/ALERTS.log"
STATUS="$LOG_DIR/LATEST_STATUS.md"
MODE_FILE="$LOG_DIR/MANAGER_MODE.txt"

notify() {
  local msg="$1"
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "[$ts] $msg" | tee -a "$ALERTS" >> "$LOG"
  if [ -n "${MANAGER_TG_TOKEN:-}" ] && [ -n "${MANAGER_TG_CHAT:-}" ]; then
    curl -sS --max-time 8 -X POST "https://api.telegram.org/bot${MANAGER_TG_TOKEN}/sendMessage" \
      -d chat_id="${MANAGER_TG_CHAT}" \
      --data-urlencode text="Ladder Watch: $msg" >/dev/null 2>&1 || true
  fi
}

eval "$(python3 - <<'PY'
from pathlib import Path
env={}
for line in Path('.env').read_text().splitlines():
    if not line.strip() or line.strip().startswith('#') or '=' not in line: continue
    k,v=line.split('=',1); env[k.strip()]=v.strip().strip('"').strip("'")
pairs=[
 ('MANAGER_TELEGRAM_TOKEN','MANAGER_TELEGRAM_CHAT_ID'),
 ('MONITOR_TELEGRAM_BOT_TOKEN','MONITOR_TELEGRAM_CHAT_ID'),
 ('TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID'),
 ('MONITOR_TELEGRAM_TOKEN','MONITOR_TELEGRAM_CHAT_ID'),
]
for t,c in pairs:
    if env.get(t) and env.get(c):
        print(f'export MANAGER_TG_TOKEN={env[t]!r}')
        print(f'export MANAGER_TG_CHAT={env[c]!r}')
        break
PY
)"

echo "WATCH_ONLY" > "$MODE_FILE"
notify "WATCH-ONLY ON | RESEARCH_ONLY | SAFE | avisa EDGE sin postear | DNA estricto"
python3 - <<PY
from pathlib import Path
Path("$STATUS").write_text("""# Ladder Manager — WATCH ONLY

- **Modo:** WATCH_ONLY (sin auto-execute, sin arm)
- **Postura:** RESEARCH_ONLY
- **SAFE:** ARMED=0 · DRY_RUN=1
- **Política:** avisa EDGE DNA; no posta órdenes
- **Rearme dinero real:** solo si `rearm_income_gate` = READY
- **Avisos:** Telegram + \`ALERTS.log\`

Última arrancada: PM2 watch-only.
""")
PY

# income-loop WITHOUT --auto-execute; --watch-only keeps scanning after edge
python -u -m polymarket.research.local_lab.definitive_income_system \
  --scale micro --income-loop --watch-only \
  --rounds 240 --interval 90 2>&1 | while IFS= read -r line; do
    echo "$line" >> "$LOG"
    if echo "$line" | grep -q '"accepted_n": 0'; then
      ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      printf '%s\n' "# Estado $ts

**Modo: WATCH_ONLY** · **WAIT** (sin take press)

Vigilando cada ~90s. No auto-execute. No fuerza near-miss.
" > "$STATUS"
    fi
    if echo "$line" | grep -q '"accepted_n": [1-9]'; then
      notify "EDGE DNA detectado — WATCH ONLY (NO se postea). Revisa y decide manual."
      ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      printf '%s\n' "# Estado $ts

**Modo: WATCH_ONLY** · **EDGE DNA** (sin post)

Aviso enviado. Dinero real OFF hasta rearm gate READY + decisión del operador.
" > "$STATUS"
    fi
    if echo "$line" | grep -q 'verdict='; then
      notify "Watch loop fin: $line"
    fi
  done

notify "WATCH-ONLY detenido (fin de rounds o crash)"
