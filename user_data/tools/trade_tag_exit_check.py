#!/usr/bin/env python3
"""
Audita que las salidas por señal de RegimeSwitcher respeten enter_tag.

Solo revisa cierres por custom_exit con tags de señal (trend_signal / mean_rev_signal).
Stoploss ATR, protecciones y trailing pueden cerrar en cualquier régimen — no son violaciones.

  docker compose run --rm --entrypoint python freqtrade \\
    user_data/tools/trade_tag_exit_check.py --strategy RegimeSwitcher --timerange 20230101-20240320
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategies"))

from freqtrade.enums import RunMode
from fixture_config import load_fixture_backtest_config
from freqtrade.exchange import Exchange
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.resolvers import StrategyResolver

from quant_core import (
  MEAN_REV_ENTER_TAG,
  MEAN_REV_SIGNAL_EXIT_TAG,
  TREND_ENTER_TAG,
  TREND_SIGNAL_EXIT_TAG,
)


SIGNAL_EXIT_REASONS = frozenset({TREND_SIGNAL_EXIT_TAG, MEAN_REV_SIGNAL_EXIT_TAG})
FORBIDDEN_SIGNAL_BY_ENTER_TAG = {
  TREND_ENTER_TAG: MEAN_REV_SIGNAL_EXIT_TAG,
  MEAN_REV_ENTER_TAG: TREND_SIGNAL_EXIT_TAG,
}


def _parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Auditoría enter_tag vs señales de salida")
  parser.add_argument("--strategy", default="RegimeSwitcher")
  parser.add_argument("--strategy-path", default="user_data/strategies")
  parser.add_argument("--config", action="append", default=[])
  parser.add_argument("--timerange", default="20240101-20240320")
  parser.add_argument(
    "--min-signal-exits",
    type=int,
    default=0,
    help="Exigir al menos N cierres por señal custom_exit (tests con stop ensanchado)",
  )
  return parser.parse_args()


def _extract_trades(backtest_result: object, strategy_name: str) -> list[dict]:
  if isinstance(backtest_result, dict):
    if "results" in backtest_result:
      results = backtest_result["results"]
      if hasattr(results, "to_dict"):
        return list(results.to_dict("records"))
    if "strategy" in backtest_result and strategy_name in backtest_result["strategy"]:
      return list(backtest_result["strategy"][strategy_name].get("trades", []))
    if strategy_name in backtest_result:
      block = backtest_result[strategy_name]
      if isinstance(block, dict) and "trades" in block:
        return list(block["trades"])
    if "trades" in backtest_result:
      return list(backtest_result["trades"])
  if isinstance(backtest_result, list) and backtest_result:
    first = backtest_result[0]
    if isinstance(first, dict) and "results" in first:
      return _extract_trades(first["results"], strategy_name)
  return []


def _trade_fee_usdt(trade: dict) -> float:
  stake = float(trade.get("stake_amount") or 0)
  fee_open = float(trade.get("fee_open") or 0)
  fee_close = float(trade.get("fee_close") or 0)
  return stake * (fee_open + fee_close)


def _print_trade_distribution(trades: list[dict]) -> None:
  by_tag = Counter(t.get("enter_tag") or "unknown" for t in trades)
  print("Trades por enter_tag:")
  for tag, count in sorted(by_tag.items()):
    pct = 100.0 * count / len(trades)
    print(f"  {tag}: {count} ({pct:.1f}%)")

  by_exit = Counter(t.get("exit_reason") or "unknown" for t in trades)
  print("Cierres por exit_reason:")
  for reason, count in by_exit.most_common():
    print(f"  {reason}: {count}")


def _print_friction_by_tag(trades: list[dict]) -> None:
  buckets: dict[str, dict[str, float]] = defaultdict(
    lambda: {"count": 0, "net": 0.0, "fees": 0.0, "gross": 0.0, "signal_exits": 0}
  )
  for trade in trades:
    tag = trade.get("enter_tag") or "unknown"
    net = float(trade.get("profit_abs") or 0)
    fees = _trade_fee_usdt(trade)
    buckets[tag]["count"] += 1
    buckets[tag]["net"] += net
    buckets[tag]["fees"] += fees
    buckets[tag]["gross"] += net + fees
    if trade.get("exit_reason") in SIGNAL_EXIT_REASONS:
      buckets[tag]["signal_exits"] += 1

  print("Fricción por enter_tag (USDT):")
  for tag in sorted(buckets):
    b = buckets[tag]
    gross = b["gross"]
    fees = b["fees"]
    net = b["net"]
    print(
      f"  {tag}: n={int(b['count'])} "
      f"bruto={gross:.2f} fees={fees:.2f} neto={net:.2f} "
      f"señales={int(b['signal_exits'])}"
    )
    if gross != 0:
      print(f"    |fees|/|bruto|={abs(fees / gross) * 100:.1f}%")


def main() -> int:
  args = _parse_args()
  root = Path("/freqtrade")
  config_files = args.config or None
  config = load_fixture_backtest_config(config_files, root=root)
  config["runmode"] = RunMode.BACKTEST
  config["strategy"] = args.strategy
  config["strategy_path"] = str(root / args.strategy_path)
  config["timerange"] = args.timerange

  exchange = Exchange(config)
  strategy = StrategyResolver.load_strategy(config)
  strategy.ft_load_hyper_params(False)

  bt = Backtesting(config, exchange)
  bt._set_strategy(strategy)
  data, timerange = bt.load_bt_data()
  if not data:
    print("FAIL: sin datos de backtest")
    return 1

  start_date = timerange.startdt
  end_date = timerange.stopdt
  processed = bt.strategy.advise_all_indicators(data)
  result = bt.backtest(processed=processed, start_date=start_date, end_date=end_date)

  trades = _extract_trades(result, args.strategy)
  if not trades:
    print(f"FAIL: 0 trades para {args.strategy} — no se puede auditar enter_tag")
    return 1

  enter_tags = {t.get("enter_tag") for t in trades if t.get("enter_tag")}
  print(f"enter_tag distintos: {sorted(enter_tags)}")
  print(f"total trades: {len(trades)}")
  _print_trade_distribution(trades)
  _print_friction_by_tag(trades)

  missing = {TREND_ENTER_TAG, MEAN_REV_ENTER_TAG} - enter_tags
  if missing:
    print(f"FAIL: faltan enter_tag {sorted(missing)} en el backtest")
    return 1

  signal_exits = [t for t in trades if t.get("exit_reason") in SIGNAL_EXIT_REASONS]
  print(f"cierres por señal custom_exit: {len(signal_exits)}")

  if args.min_signal_exits > 0 and len(signal_exits) < args.min_signal_exits:
    print(
      f"FAIL: se requieren >= {args.min_signal_exits} cierres por señal; "
      f"obtenidos {len(signal_exits)} — dispatch no ejercitado"
    )
    return 1

  violations: list[dict] = []
  for trade in signal_exits:
    enter_tag = trade.get("enter_tag")
    exit_reason = trade.get("exit_reason")
    forbidden = FORBIDDEN_SIGNAL_BY_ENTER_TAG.get(enter_tag)
    if forbidden and exit_reason == forbidden:
      violations.append(trade)

  if violations:
    print(f"FAIL: {len(violations)} trade(s) cerrados por señal de rama contraria:")
    for v in violations[:5]:
      print(
        f"  pair={v.get('pair')} enter_tag={v.get('enter_tag')} "
        f"exit_reason={v.get('exit_reason')}"
      )
    return 1

  print("OK: salidas respetan enter_tag (solo señales custom_exit auditadas)")
  return 0


if __name__ == "__main__":
  sys.exit(main())
