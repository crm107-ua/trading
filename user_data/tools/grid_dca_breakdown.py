#!/usr/bin/env python3
"""
Desglose GridDCA: ajustes de posición, exit_reason y PnL por capas.

  docker compose run --rm --entrypoint python freqtrade \\
    user_data/tools/grid_dca_breakdown.py --zip user_data/backtest_results/latest.zip

  docker compose run --rm --entrypoint python freqtrade \\
    user_data/tools/grid_dca_breakdown.py --strategy GridDCA --timerange 20230101-20240320
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategies"))

from freqtrade.enums import RunMode
from freqtrade.exchange import Exchange
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.resolvers import StrategyResolver

from fixture_config import load_fixture_backtest_config
from quant_core import count_trade_position_adjustments


def _parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Desglose GridDCA por ajustes y exit_reason")
  parser.add_argument("--strategy", default="GridDCA")
  parser.add_argument("--zip", default="", help="Ruta a backtest-result-*.zip exportado")
  parser.add_argument("--timerange", default="20230101-20240320")
  parser.add_argument("--real-data", action="store_true", help="user_data/data (no fixtures)")
  parser.add_argument(
    "--timerange-end",
    default="",
    help="ISO fin del timerange para marcar force_exit contaminante (ej. 2024-03-20)",
  )
  return parser.parse_args()


def _timerange_end_dt(timerange: str, override: str) -> datetime | None:
  if override:
    return datetime.fromisoformat(override.replace("Z", "+00:00"))
  if "-" in timerange and len(timerange.split("-", 1)[1]) >= 8:
    end = timerange.split("-", 1)[1]
    return datetime(
      int(end[0:4]), int(end[4:6]), int(end[6:8]), tzinfo=timezone.utc
    )
  return None


def _load_trades_from_zip(zip_path: Path, strategy: str) -> list[dict]:
  with zipfile.ZipFile(zip_path) as zf:
    json_name = next(n for n in zf.namelist() if n.endswith(".json") and "_config" not in n)
    payload = json.loads(zf.read(json_name))
  block = payload.get("strategy", {})
  if strategy in block:
    return list(block[strategy].get("trades", []))
  if isinstance(block, dict) and block:
    first = next(iter(block.values()))
    if isinstance(first, dict) and "trades" in first:
      return list(first["trades"])
  return []


def _run_backtest_trades(strategy: str, timerange: str, *, real_data: bool) -> list[dict]:
  root = Path("/freqtrade")
  if real_data:
    from freqtrade.configuration import Configuration

    files = [
      str(root / "user_data/config/base.json"),
      str(root / "user_data/config/backtest.json"),
    ]
    config = Configuration.from_files(files)
    if hasattr(config, "get_config"):
      config = config.get_config()
  else:
    config = load_fixture_backtest_config(root=root)

  config["runmode"] = RunMode.BACKTEST
  config["strategy"] = strategy
  config["strategy_path"] = str(root / "user_data/strategies")
  config["timerange"] = timerange

  exchange = Exchange(config)
  strat = StrategyResolver.load_strategy(config)
  strat.ft_load_hyper_params(False)
  bt = Backtesting(config, exchange)
  bt._set_strategy(strat)
  data, tr = bt.load_bt_data()
  processed = bt.strategy.advise_all_indicators(data)
  result = bt.backtest(processed=processed, start_date=tr.startdt, end_date=tr.stopdt)
  rows = result.get("results")
  if hasattr(rows, "to_dict"):
    return list(rows.to_dict("records"))
  return []


def _trade_fee_usdt(trade: dict) -> float:
  stake = float(trade.get("stake_amount") or 0)
  fee_open = float(trade.get("fee_open") or 0)
  fee_close = float(trade.get("fee_close") or 0)
  return stake * (fee_open + fee_close)


def _print_breakdown(trades: list[dict], timerange_end: datetime | None) -> int:
  if not trades:
    print("FAIL: 0 trades")
    return 1

  by_adj: dict[int, list[dict]] = defaultdict(list)
  for trade in trades:
    by_adj[count_trade_position_adjustments(trade)].append(trade)

  exit_counts = Counter(t.get("exit_reason") for t in trades)
  total_net = sum(float(t.get("profit_abs") or 0) for t in trades)
  total_fees = sum(_trade_fee_usdt(t) for t in trades)

  print(f"total trades: {len(trades)}")
  print(f"PnL neto total: {total_net:.2f} USDT | fees estimadas: {total_fees:.2f} USDT")
  print("\n=== Distribución por ajustes (compras adicionales) ===")
  for adj in sorted(by_adj):
    subset = by_adj[adj]
    net = sum(float(t.get("profit_abs") or 0) for t in subset)
    fees = sum(_trade_fee_usdt(t) for t in subset)
    gross = net + fees
    print(
      f"  {adj} ajustes: {len(subset):4d} ({100 * len(subset) / len(trades):5.1f}%) "
      f"| neto {net:8.0f} | bruto {gross:8.0f} | medio {net / len(subset):6.2f} USDT/trade"
    )

  print("\n=== exit_reason ===")
  for reason, count in exit_counts.most_common():
    print(f"  {reason}: {count} ({100 * count / len(trades):.1f}%)")

  force_exits = [t for t in trades if t.get("exit_reason") == "force_exit"]
  if force_exits:
    print("\n=== force_exit (posible contaminación de timerange) ===")
    print(f"  total: {len(force_exits)}")
    if timerange_end is not None:
      window_h = 48
      near_end = 0
      for trade in force_exits:
        close_raw = trade.get("close_date")
        if not close_raw:
          continue
        close_dt = datetime.fromisoformat(str(close_raw).replace("Z", "+00:00"))
        if (timerange_end - close_dt).total_seconds() < window_h * 3600:
          near_end += 1
      print(f"  en últimas {window_h}h del timerange: {near_end}")

  clean = [t for t in trades if t.get("exit_reason") != "force_exit"]
  if len(clean) != len(trades):
    clean_net = sum(float(t.get("profit_abs") or 0) for t in clean)
    print(f"\n=== Excluyendo force_exit ({len(clean)} trades) ===")
    print(f"  PnL neto: {clean_net:.2f} USDT")

  dca_used = sum(1 for t in trades if count_trade_position_adjustments(t) > 0)
  full_grid = len(by_adj.get(3, []))
  base_only = len(by_adj.get(0, []))
  base_net = sum(float(t.get("profit_abs") or 0) for t in by_adj.get(0, []))

  print("\n=== Lectura DCA ===")
  print(f"  trades con >=1 ajuste: {dca_used} ({100 * dca_used / len(trades):.1f}%)")
  print(f"  trades con 3 ajustes (grid completo): {full_grid} ({100 * full_grid / len(trades):.1f}%)")
  print(f"  PnL neto solo entrada base (0 ajustes): {base_net:.0f} USDT ({base_only} trades)")

  if dca_used == 0:
    print("\nWARN: ningún trade usó DCA — el backtest no ejercita la hipótesis grid")
  elif full_grid == 0:
    print("\nWARN: ningún trade completó 3 capas — defaults raramente disparan el grid en este histórico")

  return 0


def main() -> int:
  args = _parse_args()
  timerange_end = _timerange_end_dt(args.timerange, args.timerange_end)

  if args.zip:
    zip_path = Path(args.zip)
    if not zip_path.is_absolute():
      zip_path = Path("/freqtrade") / zip_path
    if not zip_path.exists():
      print(f"FAIL: no existe {zip_path}")
      return 1
    trades = _load_trades_from_zip(zip_path, args.strategy)
  else:
    trades = _run_backtest_trades(args.strategy, args.timerange, real_data=args.real_data)

  return _print_breakdown(trades, timerange_end)


if __name__ == "__main__":
  sys.exit(main())
