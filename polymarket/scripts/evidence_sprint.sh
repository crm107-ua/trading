#!/usr/bin/env bash
# Evidence sprint — dense resolve/assurance loop toward READY_TO_REARM.
# WATCH_ONLY · SAFE · never posts · never deposits.
set -euo pipefail
ROOT="${ROOT:-/var/www/html/trader}"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export POLY_LIVE_ARMED=0
export POLY_LIVE_DRY_RUN=1
unset POLY_LADDER_REAL_CONFIRM POLY_LADDER_ALLOW_REARM || true
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

RUN="$ROOT/polymarket/data_local/local_lab/vps_runs"
mkdir -p "$RUN/telemetry"
INTERVAL_SEC="${EVIDENCE_SPRINT_INTERVAL_SEC:-180}"
PY="$ROOT/.venv/bin/python"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] EVIDENCE_SPRINT ON | interval=${INTERVAL_SEC}s | NO posts" | tee -a "$RUN/ALERTS.log"

loop=0
while true; do
  loop=$((loop + 1))
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[$ts] sprint_loop=$loop" | tee -a "$RUN/evidence_sprint.log"

  "$PY" -u -m polymarket.research.local_lab.resolve_forward_cases \
    >>"$RUN/evidence_sprint.log" 2>&1 || true

  "$PY" -u -m polymarket.research.local_lab.assurance_research \
    >>"$RUN/evidence_sprint.log" 2>&1 || true

  "$PY" -u -m polymarket.research.local_lab.rearm_income_gate --balance 3.4482 \
    >>"$RUN/evidence_sprint.log" 2>&1 || true

  # Compact status for humans
  "$PY" - <<'PY' >>"$RUN/evidence_sprint.log" 2>&1 || true
import json
from pathlib import Path
from datetime import datetime, timezone
VPS=Path("polymarket/data_local/local_lab/vps_runs")
rearm=(json.loads((VPS.parent/"rearm_gate/latest.json").read_text()).get("decision")
       if (VPS.parent/"rearm_gate/latest.json").exists() else {})
ass=json.loads((VPS/"ASSURANCE_SCORECARD.json").read_text()) if (VPS/"ASSURANCE_SCORECARD.json").exists() else {}
ev=json.loads((VPS/"telemetry/EVIDENCE_PROGRESS.json").read_text()) if (VPS/"telemetry/EVIDENCE_PROGRESS.json").exists() else {}
res=json.loads((VPS/"FORWARD_RESOLVE_REPORT.json").read_text()) if (VPS/"FORWARD_RESOLVE_REPORT.json").exists() else {}
status={
  "ts_utc": datetime.now(timezone.utc).isoformat(),
  "rearm_status": rearm.get("status"),
  "can_enable_auto_execute": rearm.get("can_enable_auto_execute"),
  "can_recommend_deposit": rearm.get("can_recommend_deposit"),
  "blockers": rearm.get("blockers"),
  "assurance_grade": (ass.get("grade") or {}).get("grade"),
  "n": (ev.get("historical") or {}).get("n"),
  "wilson": (ev.get("historical") or {}).get("wilson95_lower"),
  "n_to_go_micro": ev.get("n_to_go_micro"),
  "resolve_delta_n": res.get("delta_n"),
  "cases_updated": res.get("cases_updated"),
}
(VPS/"MONEY_READY_STATUS.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
lines=[
  "# Money-ready status (investigación)",
  "",
  f"**UTC:** `{status['ts_utc']}`",
  f"**Rearm:** `{status['rearm_status']}`",
  f"**Deposit recommend:** `{status['can_recommend_deposit']}`",
  f"**Assurance ops:** `{status['assurance_grade']}`",
  f"**DNA n / Wilson:** {status['n']} / {status['wilson']} (faltan GO_MICRO: {status['n_to_go_micro']})",
  f"**Resolve Δn / updates:** {status['resolve_delta_n']} / {status['cases_updated']}",
  "",
  "## Blockers",
]
for b in status.get("blockers") or ["(none)"]:
  lines.append(f"- `{b}`")
lines += [
  "",
  "Solo meter dinero real cuando `rearm_status=READY_TO_REARM` y `can_recommend_deposit=true`.",
  "",
]
(VPS/"MONEY_READY_STATUS.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps(status, indent=2))
# Alert if READY
if status.get("rearm_status")=="READY_TO_REARM":
  print("READY_TO_REARM — operator may deposit per gate")
PY

  # If READY, notify once via alerts log (progress_watch may also catch)
  if grep -q 'READY_TO_REARM' "$RUN/MONEY_READY_STATUS.json" 2>/dev/null; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] READY_TO_REARM detected by evidence sprint" | tee -a "$RUN/ALERTS.log"
  fi

  sleep "$INTERVAL_SEC"
done
