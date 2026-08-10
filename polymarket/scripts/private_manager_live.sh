#!/usr/bin/env bash
# ARMED auto-execute manager — ONLY after rearm_income_gate = READY_TO_REARM.
# Default ops use private_manager_watch.sh (WATCH_ONLY).
set -u
cd /var/www/html/trader
source .venv/bin/activate
export PYTHONPATH=/var/www/html/trader

# Refuse to start unless operator explicitly allows rearm
if [ "${POLY_LADDER_ALLOW_REARM:-0}" != "1" ]; then
  echo "Refusing live auto-execute manager: set POLY_LADDER_ALLOW_REARM=1 only after rearm_income_gate READY"
  echo "Use: polymarket/scripts/private_manager_watch.sh"
  exit 2
fi

# Hard gate: rearm_income_gate must be READY_TO_REARM (reads live balance if possible)
echo "Checking rearm_income_gate before live manager…"
set +e
GATE_JSON=$(python - <<'PY'
import json, os, subprocess, sys
from pathlib import Path
os.environ["POLY_LIVE_ARMED"]="0"
os.environ["POLY_LIVE_DRY_RUN"]="1"
os.environ["PYTHONPATH"]="/var/www/html/trader"
bal="3.4482"
try:
    from polymarket.src.ai.env_loader import load_repo_dotenv
    load_repo_dotenv(override=True)
    from polymarket.src.execution.clob_live import ClobLiveClient, read_gates
    g=read_gates()
    if g.signing_ready:
        c=ClobLiveClient(); c.connect(derive_api_creds=True)
        b=c.balance_collateral_usdc()
        if b is not None:
            bal=str(round(float(b),4))
except Exception as e:
    print(f"balance_probe_fail={type(e).__name__}", file=sys.stderr)
proc=subprocess.run(
    [sys.executable,"-m","polymarket.research.local_lab.rearm_income_gate",
     "--balance", bal, "--run-income-tests"],
    cwd="/var/www/html/trader", capture_output=True, text=True, timeout=240,
    env={**os.environ, "PYTHONPATH":"/var/www/html/trader",
         "POLY_LIVE_ARMED":"0","POLY_LIVE_DRY_RUN":"1"},
)
latest=Path("polymarket/data_local/local_lab/rearm_gate/latest.json")
dec={}
if latest.exists():
    dec=(json.loads(latest.read_text()).get("decision") or {})
print(json.dumps({"status": dec.get("status"), "can_enable": dec.get("can_enable_auto_execute"),
                  "blockers": dec.get("blockers"), "exit": proc.returncode, "balance": bal}))
PY
)
GATE_RC=$?
set -e
echo "$GATE_JSON"
STATUS=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("status") or "")' "$GATE_JSON" 2>/dev/null || true)
if [ "$STATUS" != "READY_TO_REARM" ]; then
  echo "Refusing live manager: rearm_income_gate status='$STATUS' (need READY_TO_REARM)"
  echo "Stay on private_manager_watch.sh until evidence+capital clear."
  exit 2
fi

export POLY_LADDER_REAL_CONFIRM=1
# Start SAFE; execute path arms temporarily if edge+gates OK
export POLY_LIVE_ARMED=0
export POLY_LIVE_DRY_RUN=1

LOG_DIR=polymarket/data_local/local_lab/vps_runs
mkdir -p "$LOG_DIR"
DAY=$(date -u +%Y%m%d)
LOG="$LOG_DIR/private_manager_${DAY}.log"
ALERTS="$LOG_DIR/ALERTS.log"
STATUS_MD="$LOG_DIR/LATEST_STATUS.md"
echo "AUTO_EXECUTE_ARMED_PATH" > "$LOG_DIR/MANAGER_MODE.txt"

notify() {
  local msg="$1"
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "[$ts] $msg" | tee -a "$ALERTS" >> "$LOG"
  if [ -n "${MANAGER_TG_TOKEN:-}" ] && [ -n "${MANAGER_TG_CHAT:-}" ]; then
    curl -sS --max-time 8 -X POST "https://api.telegram.org/bot${MANAGER_TG_TOKEN}/sendMessage" \
      -d chat_id="${MANAGER_TG_CHAT}" \
      --data-urlencode text="Ladder LIVE: $msg" >/dev/null 2>&1 || true
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
]
for t,c in pairs:
    if env.get(t) and env.get(c):
        print(f'export MANAGER_TG_TOKEN={env[t]!r}')
        print(f'export MANAGER_TG_CHAT={env[c]!r}')
        break
PY
)"

notify "GESTOR AUTO-EXECUTE activo (REARM READY verificado) | DNA | balance watch"
python3 - <<PY
from pathlib import Path
Path("$STATUS_MD").write_text("""# Ladder Private Manager — AUTO-EXECUTE

- **Modo:** auto-execute DNA (tras rearm gate READY)
- **VPS:** España
- **SAFE default** hasta edge; arm temporal en post
""")
PY

python -u -m polymarket.research.local_lab.definitive_income_system \
  --scale micro --income-loop --auto-execute --i-accept-real-loss YES \
  --rounds 240 --interval 90 2>&1 | while IFS= read -r line; do
    echo "$line" >> "$LOG"
    if echo "$line" | grep -q 'INCOME_POSTED'; then
      notify "EJECUTADO REAL: INCOME_POSTED"
    fi
    if echo "$line" | grep -q 'REAL_POSTED'; then
      notify "ORDEN REAL POSTEADA"
    fi
    if echo "$line" | grep -q '"accepted_n": 0'; then
      ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      printf '%s\n' "# Estado $ts

**AUTO-EXECUTE** · WAIT (sin take)
" > "$STATUS_MD"
    fi
    if echo "$line" | grep -q '"accepted_n": [1-9]'; then
      notify "EDGE DETECTADO — intentando execute real"
      ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      printf '%s\n' "# Estado $ts

**AUTO-EXECUTE** · EDGE → execute path
" > "$STATUS_MD"
    fi
  done

notify "GESTOR AUTO-EXECUTE detenido"
