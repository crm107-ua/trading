#!/usr/bin/env python3
"""
Auditoría GridDCA: ajustes de posición, presupuesto y ciclo DCA→stop.

  docker compose run --rm --entrypoint python freqtrade \\
    user_data/tools/grid_dca_check.py --strategy GridDCA --min-position-adjustments 3
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategies"))

from freqtrade.enums import RunMode
from fixture_config import load_fixture_backtest_config
from freqtrade.exchange import Exchange
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.resolvers import StrategyResolver

from quant_core import (
  DEFAULT_GRID_MAX_POSITION_RATIO,
  count_trade_position_adjustments,
  trade_total_entry_stake,
)


def _parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Auditoría GridDCA")
  parser.add_argument("--strategy", default="GridDCA")
  parser.add_argument("--strategy-path", default="user_data/strategies")
  parser.add_argument("--config", action="append", default=[])
  parser.add_argument("--timerange", default="20240120-20240128")
  parser.add_argument(
    "--min-position-adjustments",
    type=int,
    default=0,
    help="Exigir al menos N ajustes en algún trade (compras adicionales)",
  )
  parser.add_argument(
    "--max-position-ratio",
    type=float,
    default=DEFAULT_GRID_MAX_POSITION_RATIO,
    help="Ratio de wallet para tope de presupuesto por posición",
  )
  parser.add_argument(
    "--require-stop-after-dca",
    action="store_true",
    help="Exigir al menos un trade con >=3 ajustes cerrado por stop",
  )
  parser.add_argument(
    "--pairs",
    nargs="*",
    default=[],
    help="Limitar pares (ej. BTC/USDT) para fixtures deterministas",
  )
  return parser.parse_args()


def _extract_trades(backtest_result: object) -> list[dict]:
  if isinstance(backtest_result, dict) and "results" in backtest_result:
    results = backtest_result["results"]
    if hasattr(results, "to_dict"):
      return list(results.to_dict("records"))
  return []


def _wallet_budget(config: dict, ratio: float) -> float:
  dry_wallet = float(config.get("dry_run_wallet") or 10000)
  tradable = float(config.get("tradable_balance_ratio") or 1.0)
  return dry_wallet * tradable * ratio


def main() -> int:
  args = _parse_args()
  root = Path("/freqtrade")
  config_files = args.config or None
  config = load_fixture_backtest_config(config_files, root=root)
  config["runmode"] = RunMode.BACKTEST
  config["strategy"] = args.strategy
  config["strategy_path"] = str(root / args.strategy_path)
  config["timerange"] = args.timerange
  if args.pairs:
    config["exchange"]["pair_whitelist"] = list(args.pairs)

  exchange = Exchange(config)
  strategy = StrategyResolver.load_strategy(config)
  strategy.ft_load_hyper_params(False)

  bt = Backtesting(config, exchange)
  bt._set_strategy(strategy)
  data, timerange = bt.load_bt_data()
  if not data:
    print("FAIL: sin datos de backtest")
    return 1

  processed = bt.strategy.advise_all_indicators(data)
  result = bt.backtest(
    processed=processed,
    start_date=timerange.startdt,
    end_date=timerange.stopdt,
  )

  trades = _extract_trades(result)
  if not trades:
    print(f"FAIL: 0 trades para {args.strategy}")
    return 1

  max_budget = _wallet_budget(config, args.max_position_ratio)
  adjustments_per_trade = [count_trade_position_adjustments(t) for t in trades]
  max_adj = max(adjustments_per_trade) if adjustments_per_trade else 0

  print(f"total trades: {len(trades)}")
  print(f"ajustes por trade (max): {max_adj}")
  print(f"presupuesto máximo por posición (USDT): {max_budget:.2f}")

  budget_violations: list[str] = []
  for trade in trades:
    exposure = trade_total_entry_stake(trade)
    if exposure > max_budget * 1.02:
      budget_violations.append(
        f"{trade.get('pair')} exposure={exposure:.2f}>{max_budget:.2f}"
      )

  if budget_violations:
    print(f"FAIL: {len(budget_violations)} trade(s) superan presupuesto:")
    for line in budget_violations[:5]:
      print(f"  {line}")
    return 1

  print("OK: exposición dentro de presupuesto en todos los trades")

  exit_reasons = Counter(t.get("exit_reason") for t in trades)
  print(f"Cierres por exit_reason: {dict(exit_reasons)}")

  dca_heavy = [
    t
    for t in trades
    if count_trade_position_adjustments(t) >= args.min_position_adjustments
  ]
  if args.min_position_adjustments > 0 and not dca_heavy:
    print(
      f"FAIL: ningún trade con >={args.min_position_adjustments} ajustes "
      f"(max observado: {max_adj})"
    )
    return 1

  if args.min_position_adjustments > 0:
    print(f"trades con >={args.min_position_adjustments} ajustes: {len(dca_heavy)}")

  if args.require_stop_after_dca:
    stopped = [
      t
      for t in dca_heavy
      if t.get("exit_reason") in {"stop_loss", "trailing_stop_loss"}
    ]
    if not stopped:
      print("FAIL: ningún trade DCA completo cerrado por stop global")
      return 1
    print(f"trades DCA→stop: {len(stopped)}")

  print("OK: auditoría GridDCA completada")
  return 0


if __name__ == "__main__":
  sys.exit(main())
