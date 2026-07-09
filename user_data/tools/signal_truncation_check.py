#!/usr/bin/env python3
"""
Compara enter_long / exit_long entre dataframe completo y versiones truncadas.

Criterio: cero diferencias en velas posteriores al warmup (señales = función pura del pasado).
Ejecutar dentro del contenedor Freqtrade:

  docker compose run --rm freqtrade python user_data/tools/signal_truncation_check.py \\
    --strategy MeanRevBB --timerange 20240101-20240320
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from freqtrade.configuration import Configuration
from freqtrade.enums import CandleType, RunMode
from freqtrade.exchange import Exchange, timeframe_to_prev_date
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.resolvers import StrategyResolver


def _parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Validación de señales sin lookahead (truncación)")
  parser.add_argument("--strategy", required=True)
  parser.add_argument("--strategy-path", default="user_data/strategies")
  parser.add_argument("--config", action="append", default=[])
  parser.add_argument("--timerange", default="20240101-20240320")
  parser.add_argument("--cut-samples", type=int, default=20, help="Puntos de corte tras warmup")
  return parser.parse_args()


class _TruncatingDataProvider:
  """Envuelve DataProvider limitando get_pair_dataframe al corte causal."""

  def __init__(self, base: object, cut_time: pd.Timestamp) -> None:
    self._base = base
    self._cut = pd.Timestamp(cut_time)
    if self._cut.tzinfo is None:
      self._cut = self._cut.tz_localize("UTC")

  def get_pair_dataframe(
    self,
    pair: str,
    timeframe: str | None = None,
    candle_type: CandleType = CandleType.SPOT,
  ) -> pd.DataFrame:
    df = self._base.get_pair_dataframe(pair=pair, timeframe=timeframe, candle_type=candle_type)
    if df is None or df.empty:
      return df
    dates = pd.to_datetime(df["date"], utc=True)
    return df.loc[dates <= self._cut].copy()

  def __getattr__(self, name: str) -> object:
    return getattr(self._base, name)


def _signal_value(row: pd.Series, column: str) -> int:
  if column not in row.index:
    return 0
  val = row[column]
  if pd.isna(val):
    return 0
  return int(val)


def _analyze_pair_signals(
  strategy: object,
  pair: str,
  dataframe: pd.DataFrame,
  warmup: int,
  cut_samples: int,
) -> list[tuple[str, object, str, int, int]]:
  metadata = {"pair": pair}
  mismatches: list[tuple[str, object, str, int, int]] = []

  df_full = strategy.advise_indicators(dataframe.copy(), metadata)
  df_full = strategy.advise_entry(df_full, metadata)
  df_full = strategy.advise_exit(df_full, metadata)

  n = len(df_full)
  if n <= warmup:
    return mismatches

  step = max(1, (n - warmup) // cut_samples)
  indices = list(range(warmup, n, step))
  if indices[-1] != n - 1:
    indices.append(n - 1)

  orig_dp = strategy.dp
  timeframe = strategy.timeframe

  for cut_idx in indices:
    cut_time = pd.Timestamp(df_full.iloc[cut_idx]["date"])
    strategy.dp = _TruncatingDataProvider(orig_dp, cut_time)

    df_trunc_raw = strategy.dp.get_pair_dataframe(pair, timeframe)
    if df_trunc_raw is None or df_trunc_raw.empty:
      strategy.dp = orig_dp
      continue

    df_trunc = strategy.advise_indicators(df_trunc_raw.copy(), metadata)
    df_trunc = strategy.advise_entry(df_trunc, metadata)
    df_trunc = strategy.advise_exit(df_trunc, metadata)

    candle_start = timeframe_to_prev_date(timeframe, cut_time)
    dates_full = pd.to_datetime(df_full["date"], utc=True)
    cs = pd.Timestamp(candle_start)
    if cs.tzinfo is None and dates_full.dt.tz is not None:
      cs = cs.tz_localize("UTC")

    match_full = df_full.loc[dates_full == cs]
    if match_full.empty:
      row_full = df_full.iloc[cut_idx]
    else:
      row_full = match_full.iloc[-1]

    row_trunc = df_trunc.iloc[-1]

    for col in ("enter_long", "exit_long"):
      v_full = _signal_value(row_full, col)
      v_trunc = _signal_value(row_trunc, col)
      if v_full != v_trunc:
        mismatches.append((pair, cut_time, col, v_full, v_trunc))

  strategy.dp = orig_dp
  return mismatches


def _load_pair_df(data: dict, pair: str, timeframe: str) -> pd.DataFrame | None:
  key = (pair, timeframe, CandleType.SPOT)
  if key in data:
    return data[key]
  key2 = (pair, timeframe)
  if key2 in data:
    return data[key2]
  if pair in data:
    return data[pair]
  for k, df in data.items():
    if isinstance(k, tuple) and k[0] == pair and k[1] == timeframe:
      return df
  return None


def main() -> int:
  args = _parse_args()
  root = Path("/freqtrade")
  config_files = args.config or [
    str(root / "user_data/config/base.json"),
    str(root / "user_data/config/backtest.json"),
  ]

  config = Configuration.from_files(config_files)
  if hasattr(config, "get_config"):
    config = config.get_config()
  config["runmode"] = RunMode.BACKTEST
  config["strategy"] = args.strategy
  config["strategy_path"] = str(root / args.strategy_path)
  config["timerange"] = args.timerange

  exchange = Exchange(config)
  strategy = StrategyResolver.load_strategy(config)
  strategy.ft_load_hyper_params(False)

  bt = Backtesting(config, exchange)
  bt._set_strategy(strategy)
  data, _timerange = bt.load_bt_data()

  pairs = config["exchange"]["pair_whitelist"]
  warmup = int(strategy.startup_candle_count)
  all_mismatches: list[tuple[str, object, str, int, int]] = []

  for pair in pairs:
    df = _load_pair_df(data, pair, strategy.timeframe)
    if df is None or df.empty:
      continue
    all_mismatches.extend(
      _analyze_pair_signals(strategy, pair, df, warmup, args.cut_samples)
    )

  if all_mismatches:
    print(f"FAIL: {len(all_mismatches)} diferencias de señal (enter_long/exit_long)")
    for row in all_mismatches[:15]:
      print(f"  {row[0]} @ {row[1]} {row[2]}: full={row[3]} trunc={row[4]}")
    if len(all_mismatches) > 15:
      print(f"  ... y {len(all_mismatches) - 15} más")
    return 1

  print(
    f"OK: señales idénticas en {args.cut_samples}+ puntos de corte "
    f"(warmup={warmup}, estrategia={args.strategy})"
  )
  return 0


if __name__ == "__main__":
  sys.exit(main())
