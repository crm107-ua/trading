#!/usr/bin/env python3
"""
Go-live checklist — se niega a continuar si algo falla (sin skip silencioso).

Uso:
  python scripts/go_live_check.py --strategy XSecMomentum
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = ROOT / "user_data" / "validation_reports"
DRYRUN_DB = ROOT / "user_data" / "dryrun_xsec.sqlite"
GAP_REPORT = ROOT / "user_data" / "dryrun_gap_report.json"
LIVE_CONFIG = ROOT / "user_data" / "config" / "live.example.json"

MIN_DRYRUN_WEEKS = 4
MIN_REBALANCES = 4


@dataclass
class CheckResult:
  name: str
  status: str  # PASS | FAIL | MANUAL
  detail: str


def check_verdict_robusta(strategy: str) -> CheckResult:
  reports = sorted(VALIDATION_DIR.glob(f"{strategy}/*/report.json"), reverse=True)
  if not reports:
    return CheckResult(
      "verdict_robusta",
      "FAIL",
      f"sin report.json en {VALIDATION_DIR / strategy}",
    )
  data = json.loads(reports[0].read_text(encoding="utf-8"))
  verdict = str(data.get("verdict") or data.get("overall_verdict") or "").upper()
  if verdict == "ROBUSTA":
    return CheckResult("verdict_robusta", "PASS", f"veredicto {verdict} en {reports[0]}")
  return CheckResult("verdict_robusta", "FAIL", f"veredicto={verdict or 'ausente'} en {reports[0]}")


def check_dryrun_duration() -> CheckResult:
  meta = ROOT / "user_data" / "dryrun_xsec_started.json"
  if not meta.is_file():
    return CheckResult("dryrun_duration", "FAIL", "sin dryrun_xsec_started.json")
  started = datetime.fromisoformat(json.loads(meta.read_text())["started_at"])
  age = datetime.now(timezone.utc) - started
  if age < timedelta(weeks=MIN_DRYRUN_WEEKS):
    return CheckResult(
      "dryrun_duration",
      "FAIL",
      f"edad {age.days}d < {MIN_DRYRUN_WEEKS} semanas",
    )
  return CheckResult("dryrun_duration", "PASS", f"edad {age.days}d")


def check_dryrun_rebalances() -> CheckResult:
  if not DRYRUN_DB.is_file():
    return CheckResult("dryrun_rebalances", "FAIL", "sin dryrun_xsec.sqlite")
  conn = sqlite3.connect(DRYRUN_DB)
  try:
    n = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
  except sqlite3.Error as exc:
    return CheckResult("dryrun_rebalances", "FAIL", str(exc))
  finally:
    conn.close()
  if n < MIN_REBALANCES:
    return CheckResult(
      "dryrun_rebalances",
      "FAIL",
      f"trades={n} < {MIN_REBALANCES} rebalanceos mínimos",
    )
  return CheckResult("dryrun_rebalances", "PASS", f"trades={n}")


def check_gap_report() -> CheckResult:
  if not GAP_REPORT.is_file():
    return CheckResult("brecha_criterios", "FAIL", f"sin {GAP_REPORT}")
  data = json.loads(GAP_REPORT.read_text(encoding="utf-8"))
  if data.get("within_pnl_threshold") is True:
    return CheckResult("brecha_criterios", "PASS", "PnL relativo dentro de umbral")
  return CheckResult(
    "brecha_criterios",
    "FAIL",
    f"brecha fuera de umbral o sin datos: {data.get('pnl_relative_divergence')}",
  )


def check_withdraw_permission(manual_ok: bool) -> CheckResult:
  if not manual_ok:
    return CheckResult(
      "api_keys_no_withdraw",
      "MANUAL",
      "confirmar manualmente: claves API sin permiso de retiro",
    )
  return CheckResult("api_keys_no_withdraw", "PASS", "confirmado por operador")


def check_stoploss_on_exchange() -> CheckResult:
  if not LIVE_CONFIG.is_file():
    return CheckResult("stoploss_on_exchange", "FAIL", f"sin {LIVE_CONFIG}")
  cfg = json.loads(LIVE_CONFIG.read_text(encoding="utf-8"))
  val = cfg.get("order_types", {}).get("stoploss_on_exchange")
  if val is True:
    return CheckResult("stoploss_on_exchange", "PASS", "stoploss_on_exchange=true en live.example")
  return CheckResult(
    "stoploss_on_exchange",
    "FAIL",
    f"stoploss_on_exchange={val} — debe ser true en config real",
  )


def run_checks(strategy: str, *, manual_withdraw: bool = False) -> list[CheckResult]:
  return [
    check_verdict_robusta(strategy),
    check_dryrun_duration(),
    check_dryrun_rebalances(),
    check_gap_report(),
    check_withdraw_permission(manual_withdraw),
    check_stoploss_on_exchange(),
  ]


def main() -> int:
  import argparse

  parser = argparse.ArgumentParser(description="Go-live checklist")
  parser.add_argument("--strategy", default="XSecMomentum")
  parser.add_argument("--manual-withdraw-ok", action="store_true")
  args = parser.parse_args()

  results = run_checks(args.strategy, manual_withdraw=args.manual_withdraw_ok)
  blocked = False
  for r in results:
    icon = {"PASS": "OK", "FAIL": "FAIL", "MANUAL": "MANUAL"}[r.status]
    print(f"[{icon}] {r.name}: {r.detail}")
    if r.status != "PASS":
      blocked = True

  if blocked:
    print("\nGO-LIVE BLOQUEADO — corregir checks en FAIL/MANUAL antes de continuar.", file=sys.stderr)
    return 1
  print("\nGO-LIVE: todos los checks PASS.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
