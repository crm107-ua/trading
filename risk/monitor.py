"""
Monitor del dry-run XSecMomentum — alertas vía API REST (puerto 8082).

Uso:
  python -m risk.monitor --once          # un ciclo (tests / cron)
  python -m risk.monitor                 # bucle cada 5 min
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from base64 import b64encode
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "user_data" / "dryrun_monitor_state.json"
ALERT_FLAG = ROOT / "user_data" / "dryrun_monitor_alert.flag"
DEFAULT_API = "http://127.0.0.1:8082"
POLL_SEC = 300
MAX_DD_PCT = 15.0
MAX_OPEN_DAYS = 21
ALLOWED_ENTRY_WEEKDAYS = {0, 1}  # lunes señal / martes open


@dataclass
class Alert:
  code: str
  message: str
  severity: str = "warning"


@dataclass
class MonitorState:
  ts: str
  api_url: str
  bot_ok: bool
  open_trades: int
  alerts: list[Alert] = field(default_factory=list)
  profit_total: float | None = None
  max_drawdown_pct: float | None = None
  rebalance_entries_checked: int = 0


def _auth_header() -> dict[str, str]:
  user = os.environ.get("FREQTRADE__API_SERVER__USERNAME", "")
  pwd = os.environ.get("FREQTRADE__API_SERVER__PASSWORD", "")
  if not user and not pwd:
    return {}
  token = b64encode(f"{user}:{pwd}".encode()).decode()
  return {"Authorization": f"Basic {token}"}


def api_get(base: str, path: str, timeout: float = 10.0) -> tuple[int, object]:
  url = f"{base.rstrip('/')}{path}"
  req = urllib.request.Request(url, headers=_auth_header())
  try:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
      return resp.status, json.loads(resp.read().decode())
  except urllib.error.HTTPError as exc:
    body = exc.read().decode(errors="replace")
    try:
      payload = json.loads(body)
    except json.JSONDecodeError:
      payload = {"error": body}
    return exc.code, payload
  except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
    return 0, {"error": str(exc)}


def evaluate_alerts(
  *,
  ping_ok: bool,
  open_trades: list[dict],
  profit_payload: dict | None,
) -> list[Alert]:
  alerts: list[Alert] = []
  if not ping_ok:
    alerts.append(Alert("bot_down", "API dry-run no responde (ping falló)", "critical"))

  if profit_payload:
    dd = profit_payload.get("max_drawdown")
    if dd is not None:
      dd_pct = abs(float(dd)) * 100.0 if abs(float(dd)) <= 1.0 else abs(float(dd))
      if dd_pct > MAX_DD_PCT:
        alerts.append(
          Alert(
            "drawdown_high",
            f"Drawdown dry-run {dd_pct:.1f}% > {MAX_DD_PCT}%",
            "warning",
          )
        )

  now = datetime.now(timezone.utc)
  for t in open_trades:
    od = t.get("open_date") or t.get("open_timestamp")
    if not od:
      continue
    if isinstance(od, (int, float)):
      open_dt = datetime.fromtimestamp(od / 1000, tz=timezone.utc)
    else:
      open_dt = datetime.fromisoformat(str(od).replace("Z", "+00:00"))
    days = (now - open_dt).total_seconds() / 86400.0
    if days > MAX_OPEN_DAYS:
      alerts.append(
        Alert(
          "stale_position",
          f"Trade {t.get('pair')} abierto {days:.0f}d > {MAX_OPEN_DAYS}d",
          "warning",
        )
      )

  return alerts


def check_entry_weekdays(recent_trades: list[dict]) -> list[Alert]:
  alerts: list[Alert] = []
  for t in recent_trades:
    od = t.get("open_date") or t.get("open_timestamp")
    if not od:
      continue
    if isinstance(od, (int, float)):
      open_dt = datetime.fromisoformat(
        datetime.fromtimestamp(od / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
      )
    else:
      open_dt = datetime.fromisoformat(str(od).replace("Z", "+00:00"))
    wd = open_dt.weekday()
    if wd not in ALLOWED_ENTRY_WEEKDAYS:
      alerts.append(
        Alert(
          "rebalance_timing_violation",
          f"Entrada {t.get('pair')} en weekday={wd} (esperado lun/mar)",
          "critical",
        )
      )
  return alerts


def poll_once(api_base: str = DEFAULT_API) -> MonitorState:
  status_ping, ping_body = api_get(api_base, "/api/v1/ping")
  ping_ok = status_ping == 200

  open_trades: list[dict] = []
  if ping_ok:
    _, status_body = api_get(api_base, "/api/v1/status")
    if isinstance(status_body, list):
      open_trades = status_body

  profit_payload = None
  if ping_ok:
    _, profit_body = api_get(api_base, "/api/v1/profit")
    if isinstance(profit_body, dict):
      profit_payload = profit_body

  recent: list[dict] = []
  if ping_ok:
    _, trades_body = api_get(api_base, "/api/v1/trades?limit=50")
    if isinstance(trades_body, dict):
      recent = list(trades_body.get("trades") or [])

  alerts = evaluate_alerts(ping_ok=ping_ok, open_trades=open_trades, profit_payload=profit_payload)
  alerts.extend(check_entry_weekdays(recent))

  dd_pct = None
  profit_total = None
  if profit_payload:
    profit_total = profit_payload.get("profit_closed_coin") or profit_payload.get("profit_all_coin")
    dd = profit_payload.get("max_drawdown")
    if dd is not None:
      dd_pct = abs(float(dd)) * 100.0 if abs(float(dd)) <= 1.0 else abs(float(dd))

  return MonitorState(
    ts=datetime.now(timezone.utc).isoformat(),
    api_url=api_base,
    bot_ok=ping_ok,
    open_trades=len(open_trades),
    alerts=alerts,
    profit_total=float(profit_total) if profit_total is not None else None,
    max_drawdown_pct=dd_pct,
    rebalance_entries_checked=len(recent),
  )


def write_state(state: MonitorState) -> None:
  STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
  payload = asdict(state)
  payload["alerts"] = [asdict(a) for a in state.alerts]
  STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
  if state.alerts:
    ALERT_FLAG.write_text(state.ts, encoding="utf-8")
  elif ALERT_FLAG.exists():
    ALERT_FLAG.unlink(missing_ok=True)


def notify_telegram(alerts: list[Alert]) -> None:
  token = os.environ.get("FREQTRADE__TELEGRAM__TOKEN", "")
  chat = os.environ.get("FREQTRADE__TELEGRAM__CHAT_ID", "")
  if not token or not chat or not alerts:
    return
  text = "[xsec-dryrun] " + "; ".join(a.message for a in alerts[:5])
  url = f"https://api.telegram.org/bot{token}/sendMessage"
  body = json.dumps({"chat_id": chat, "text": text}).encode()
  req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
  try:
    urllib.request.urlopen(req, timeout=15)
  except urllib.error.URLError:
    pass


def main() -> int:
  parser = argparse.ArgumentParser(description="Monitor dry-run XSecMomentum")
  parser.add_argument("--api", default=os.environ.get("XSEC_DRYRUN_API", DEFAULT_API))
  parser.add_argument("--once", action="store_true")
  parser.add_argument("--interval", type=int, default=POLL_SEC)
  args = parser.parse_args()

  if args.once:
    state = poll_once(args.api)
    write_state(state)
    notify_telegram(state.alerts)
    if state.alerts:
      for a in state.alerts:
        print(f"ALERT [{a.severity}] {a.code}: {a.message}", file=sys.stderr)
    print(json.dumps(asdict(state), default=str, indent=2))
    return 0

  while True:
    state = poll_once(args.api)
    write_state(state)
    notify_telegram(state.alerts)
    time.sleep(max(60, args.interval))


if __name__ == "__main__":
  raise SystemExit(main())
