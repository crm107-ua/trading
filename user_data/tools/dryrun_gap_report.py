#!/usr/bin/env python3
"""
Comparador de brecha dry-run ↔ backtest (mismo timerange).

Uso futuro (post-veredicto):
  python user_data/tools/dryrun_gap_report.py --db user_data/dryrun_xsec.sqlite \\
    --backtest-zip path/to.zip --timerange 20250701-20250711

Hoy: tests con sqlite + zip sintéticos.
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MAX_PNL_REL_DIVERGENCE = 0.30
ALLOWED_ENTRY_WEEKDAYS = {0, 1}


@dataclass
class TradeRow:
  pair: str
  open_date: str
  close_date: str | None
  open_rate: float
  close_rate: float | None
  profit_abs: float
  is_open: bool


@dataclass
class GapReport:
  timerange: str
  dryrun_trades: int
  backtest_trades: int
  dryrun_pnl: float
  backtest_pnl: float
  pnl_relative_divergence: float | None
  slippage_mean_pct: float | None
  rebalance_timing_ok_pct: float | None
  within_pnl_threshold: bool | None
  notes: list[str]


def load_trades_from_sqlite(db_path: Path) -> list[TradeRow]:
  conn = sqlite3.connect(db_path)
  conn.row_factory = sqlite3.Row
  try:
    rows = conn.execute(
      """
      SELECT pair, open_date, close_date, open_rate, close_rate,
             close_profit_abs, is_open
      FROM trades
      ORDER BY open_date
      """
    ).fetchall()
  finally:
    conn.close()
  out: list[TradeRow] = []
  for r in rows:
    out.append(
      TradeRow(
        pair=r["pair"],
        open_date=str(r["open_date"]),
        close_date=str(r["close_date"]) if r["close_date"] else None,
        open_rate=float(r["open_rate"]),
        close_rate=float(r["close_rate"]) if r["close_rate"] is not None else None,
        profit_abs=float(r["close_profit_abs"] or 0.0),
        is_open=bool(r["is_open"]),
      )
    )
  return out


def load_trades_from_zip(zip_path: Path, strategy: str = "XSecMomentum") -> list[TradeRow]:
  with zipfile.ZipFile(zip_path) as zf:
    j = next(n for n in zf.namelist() if n.endswith(".json") and "_config" not in n and "meta" not in n)
    raw = json.loads(zf.read(j))["strategy"][strategy]["trades"]
  out: list[TradeRow] = []
  for t in raw:
    out.append(
      TradeRow(
        pair=t["pair"],
        open_date=t["open_date"],
        close_date=t.get("close_date"),
        open_rate=float(t["open_rate"]),
        close_rate=float(t["close_rate"]) if t.get("close_rate") else None,
        profit_abs=float(t.get("profit_abs") or 0.0),
        is_open=not bool(t.get("is_open") is False and t.get("close_date")),
      )
    )
  return out


def _parse_ts(s: str) -> float:
  from datetime import datetime

  return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _in_timerange(ts: str, start: str | None, end: str | None) -> bool:
  t = _parse_ts(ts)
  if start:
    if t < _parse_ts(start if "T" in start else f"{start}T00:00:00+00:00"):
      return False
  if end:
    if t > _parse_ts(end if "T" in end else f"{end}T23:59:59+00:00"):
      return False
  return True


def filter_timerange(trades: list[TradeRow], timerange: str) -> list[TradeRow]:
  if "-" not in timerange:
    return trades
  start, end = timerange.split("-", 1)
  end = end or None
  return [t for t in trades if _in_timerange(t.open_date, start or None, end)]


def compute_gap(
  dry: list[TradeRow],
  bt: list[TradeRow],
  *,
  timerange: str,
) -> GapReport:
  dry_f = filter_timerange(dry, timerange)
  bt_f = filter_timerange(bt, timerange)
  dry_pnl = sum(t.profit_abs for t in dry_f)
  bt_pnl = sum(t.profit_abs for t in bt_f)
  rel_div = None
  within = None
  if abs(bt_pnl) > 1e-6:
    rel_div = abs(dry_pnl - bt_pnl) / abs(bt_pnl)
    within = rel_div < MAX_PNL_REL_DIVERGENCE

  slippages: list[float] = []
  bt_by_pair_date = {(t.pair, t.open_date[:10]): t for t in bt_f}
  for d in dry_f:
    key = (d.pair, d.open_date[:10])
    b = bt_by_pair_date.get(key)
    if b and b.open_rate > 0:
      slippages.append((d.open_rate - b.open_rate) / b.open_rate * 100.0)

  timing_ok = 0
  for d in dry_f:
    from datetime import datetime

    wd = datetime.fromisoformat(d.open_date.replace("Z", "+00:00")).weekday()
    if wd in ALLOWED_ENTRY_WEEKDAYS:
      timing_ok += 1
  timing_pct = timing_ok / len(dry_f) if dry_f else None

  notes = []
  if not dry_f:
    notes.append("sin trades dry-run en timerange")
  if not bt_f:
    notes.append("sin trades backtest en timerange")

  return GapReport(
    timerange=timerange,
    dryrun_trades=len(dry_f),
    backtest_trades=len(bt_f),
    dryrun_pnl=dry_pnl,
    backtest_pnl=bt_pnl,
    pnl_relative_divergence=rel_div,
    slippage_mean_pct=(sum(slippages) / len(slippages)) if slippages else None,
    rebalance_timing_ok_pct=timing_pct,
    within_pnl_threshold=within,
    notes=notes,
  )


def main() -> int:
  import argparse

  parser = argparse.ArgumentParser(description="Comparador brecha dry-run vs backtest")
  parser.add_argument("--db", type=Path, required=True)
  parser.add_argument("--backtest-zip", type=Path, required=True)
  parser.add_argument("--timerange", required=True)
  parser.add_argument("--output", type=Path, default=None)
  args = parser.parse_args()

  report = compute_gap(
    load_trades_from_sqlite(args.db),
    load_trades_from_zip(args.backtest_zip),
    timerange=args.timerange,
  )
  payload = asdict(report)
  text = json.dumps(payload, indent=2)
  if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
  print(text)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
