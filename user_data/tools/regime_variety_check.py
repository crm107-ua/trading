#!/usr/bin/env python3
"""
Verifica que btc_market_regime varíe sobre fixtures BULL+RANGE.

Detecta regresiones donde el informative no fusiona y el régimen quedaría
degradado silenciosamente a un valor constante.

  docker compose run --rm --entrypoint python freqtrade \\
    user_data/tools/regime_variety_check.py --strategy TrendRider
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from freqtrade.enums import RunMode
from fixture_config import load_fixture_backtest_config
from freqtrade.exchange import Exchange
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.resolvers import StrategyResolver


def _parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Régimen BTC no constante en fixtures")
  parser.add_argument("--strategy", default="TrendRider")
  parser.add_argument("--strategy-path", default="user_data/strategies")
  parser.add_argument("--config", action="append", default=[])
  parser.add_argument("--timerange", default="20240101-20240320")
  parser.add_argument("--pair", default="BTC/USDT")
  parser.add_argument("--min-distinct", type=int, default=2)
  return parser.parse_args()


def _load_pair_df(data: dict, pair: str, timeframe: str) -> pd.DataFrame | None:
  key = (pair, timeframe)
  if key in data:
    return data[key]
  for k, df in data.items():
    if isinstance(k, tuple) and k[0] == pair and k[1] == timeframe:
      return df
    if k == pair:
      return df
  return None


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
  data, _ = bt.load_bt_data()

  df = _load_pair_df(data, args.pair, strategy.timeframe)
  if df is None or df.empty:
    print(f"FAIL: sin datos para {args.pair} {strategy.timeframe}")
    return 1

  analyzed = strategy.advise_indicators(df.copy(), {"pair": args.pair})
  if "btc_market_regime" not in analyzed.columns:
    print("FAIL: columna btc_market_regime ausente tras advise_indicators")
    return 1

  dates = pd.to_datetime(analyzed["date"], utc=True)
  tr = args.timerange
  t0 = pd.Timestamp(f"{tr[:4]}-{tr[4:6]}-{tr[6:8]}", tz="UTC")
  t1 = pd.Timestamp(f"{tr[9:13]}-{tr[13:15]}-{tr[15:17]}", tz="UTC")

  window = analyzed.loc[(dates >= t0) & (dates <= t1)]
  labels = window["btc_market_regime"].dropna()
  distinct = labels.nunique()
  total = len(labels)

  counts = labels.value_counts()
  print(
    f"btc_market_regime en {args.pair} ({strategy.timeframe}): "
    f"{distinct} valores distintos — {counts.to_dict()}"
  )
  if total > 0:
    print("Distribución (% velas en ventana):")
    for regime, count in counts.items():
      pct = 100.0 * count / total
      print(f"  {regime}: {count}/{total} ({pct:.1f}%)")

  if distinct < args.min_distinct:
    print(
      f"FAIL: régimen constante o degenerado (distinct={distinct}, "
      f"mínimo={args.min_distinct})"
    )
    return 1

  print("OK: régimen variado — informative fusionado correctamente")
  return 0


if __name__ == "__main__":
  sys.exit(main())
