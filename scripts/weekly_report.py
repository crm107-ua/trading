#!/usr/bin/env python3
"""
Reporte semanal — dry-run XSecMomentum + estado pipeline.

Uso manual:
  python scripts/weekly_report.py
  python scripts/weekly_report.py --output user_data/reports/weekly/2026-W28.md
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONITOR_STATE = ROOT / "user_data" / "dryrun_monitor_state.json"
DRYRUN_DB = ROOT / "user_data" / "dryrun_xsec.sqlite"
REPORTS_DIR = ROOT / "user_data" / "reports" / "weekly"


def _load_monitor() -> dict:
  if not MONITOR_STATE.is_file():
    return {}
  return json.loads(MONITOR_STATE.read_text(encoding="utf-8"))


def _pipeline_status() -> dict:
  try:
    from pipeline.run_lock import read_lock

    lock = read_lock()
    if lock is None:
      return {"locked": False}
    return {
      "locked": True,
      "strategy": lock.strategy,
      "run_id": lock.run_id,
      "pid": lock.pid,
      "started_at": lock.started_at,
    }
  except Exception as exc:
    return {"error": str(exc)}


def _dryrun_stats() -> dict:
  if not DRYRUN_DB.is_file():
    return {"db_exists": False}
  conn = sqlite3.connect(DRYRUN_DB)
  try:
    n_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    n_open = conn.execute("SELECT COUNT(*) FROM trades WHERE is_open=1").fetchone()[0]
    rebalance_entries = conn.execute(
      """
      SELECT COUNT(*) FROM trades
      WHERE CAST(strftime('%w', open_date) AS INTEGER) IN (1, 2)
      """
    ).fetchone()[0]
    return {
      "db_exists": True,
      "trades_total": int(n_trades),
      "trades_open": int(n_open),
      "entries_mon_tue": int(rebalance_entries),
    }
  except sqlite3.Error as exc:
    return {"db_exists": True, "error": str(exc)}
  finally:
    conn.close()


def build_report_markdown() -> str:
  now = datetime.now(timezone.utc)
  mon = _load_monitor()
  pipe = _pipeline_status()
  dry = _dryrun_stats()
  lines = [
    f"# Reporte semanal dry-run XSecMomentum-m35",
    f"",
    f"Generado: {now.isoformat()}",
    f"",
    f"## Dry-run",
    f"",
    f"| Campo | Valor |",
    f"|-------|-------|",
    f"| API OK | {mon.get('bot_ok', 'n/d')} |",
    f"| Trades abiertos (API) | {mon.get('open_trades', 'n/d')} |",
    f"| PnL cerrado (API) | {mon.get('profit_total', 'n/d')} |",
    f"| Max DD % (API) | {mon.get('max_drawdown_pct', 'n/d')} |",
    f"| DB trades | {dry.get('trades_total', 0)} |",
    f"| Entradas lun/mar (DB) | {dry.get('entries_mon_tue', 0)} |",
    f"",
    f"### Alertas activas",
    f"",
  ]
  alerts = mon.get("alerts") or []
  if not alerts:
    lines.append("_Ninguna_")
  else:
    for a in alerts:
      lines.append(f"- **{a.get('code')}**: {a.get('message')}")
  lines.extend(
    [
      f"",
      f"## Pipeline validación",
      f"",
      f"```json",
      json.dumps(pipe, indent=2),
      f"```",
      f"",
      f"## Notas",
      f"",
      f"- Datos del dry-run **no** se usan para ajustar validación (ver `docs/dryrun_protocol.md`).",
      f"- Programar en Windows: Tarea Programada -> `python scripts/weekly_report.py` semanal.",
      f"",
    ]
  )
  return "\n".join(lines)


def main() -> int:
  import argparse

  parser = argparse.ArgumentParser()
  parser.add_argument("--output", type=Path, default=None)
  args = parser.parse_args()
  md = build_report_markdown()
  out = args.output
  if out is None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    iso = datetime.now(timezone.utc).strftime("%G-W%V")
    out = REPORTS_DIR / f"{iso}.md"
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text(md, encoding="utf-8")
  print(md)
  print(f"\nWrote: {out}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
