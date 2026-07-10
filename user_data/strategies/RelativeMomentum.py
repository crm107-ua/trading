"""
RelativeMomentum — momentum cross-sectional entre 5 pares USDT.

Ranking en 1d (informative), operativa en 1h. Solo entradas con régimen BTC != BEAR.
Salidas por rotación (custom_exit) + stop ATR de la base.

max_open_trades efectivo = top_n (configurar en backtest/live >= top_n hyperopt).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pandas import DataFrame
from freqtrade.strategy import IntParameter, Trade, merge_informative_pair

from quant_core import MarketRegime, column_value_at_time, compute_startup_candle_count
from _base import QuantBaseStrategy
from relative_momentum_core import (
  REL_MOMENTUM_ENTER_TAG,
  REL_MOMENTUM_EXIT_TAG,
  UNIVERSE_ASSETS,
  build_pair_ranks,
  rotation_entry_mask_daily,
  rotation_exit_mask,
  universe_daily_close_column,
)


class RelativeMomentum(QuantBaseStrategy):
  timeframe = "1h"
  can_short = False

  minimal_roi = {"0": 100}
  use_exit_signal = True

  # Con top_n=1..2, el exchange debe permitir al menos 2 slots abiertos en config.
  # La estrategia no fija max_open_trades (vive en config); relación: slots >= top_n.

  momentum_window = IntParameter(7, 30, default=14, space="buy", optimize=True)
  top_n = IntParameter(1, 2, default=1, space="buy", optimize=True)
  # Días consecutivos en top-N (ranking 1d), no velas 1h — ver rotation_entry_mask_daily.
  confirm_bars = IntParameter(1, 5, default=2, space="buy", optimize=True)
  exit_rank_k = IntParameter(2, 3, default=2, space="buy", optimize=True)

  startup_candle_count = compute_startup_candle_count("1h") + 30 * 24

  def informative_pairs(self) -> list[tuple[str, str]]:
    stake = self.config["stake_currency"]
    daily = [(f"{asset}/{stake}", "1d") for asset in UNIVERSE_ASSETS]
    return daily + super().informative_pairs()

  def _merge_universe_1d(self, dataframe: DataFrame) -> tuple[DataFrame, dict[str, str]]:
    """Fusiona cierres 1d de todo el universo (merge asof hacia atrás, ffill)."""
    asset_columns: dict[str, str] = {}
    if self.dp is None:
      return dataframe, asset_columns

    stake = self.config["stake_currency"]
    for asset in UNIVERSE_ASSETS:
      pair = f"{asset}/{stake}"
      informative = self.dp.get_pair_dataframe(pair=pair, timeframe="1d")
      if informative is None or informative.empty:
        continue
      informative = informative.copy()
      dataframe = merge_informative_pair(
        dataframe,
        informative,
        self.timeframe,
        "1d",
        ffill=True,
        append_timeframe=False,
        suffix=asset.lower(),
      )
      asset_columns[asset] = universe_daily_close_column(asset)
    return dataframe, asset_columns

  def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = super().populate_indicators(dataframe, metadata)
    dataframe, asset_columns = self._merge_universe_1d(dataframe)

    window = int(self.momentum_window.value)
    ranks = build_pair_ranks(dataframe, asset_columns=asset_columns, window=window)
    if ranks.empty:
      dataframe["rel_momentum_rank"] = float("nan")
      dataframe["exit_cond_rotation"] = False
      return dataframe

    pair = metadata["pair"]
    stake = self.config["stake_currency"]
    asset = pair.split("/")[0] if "/" in pair else pair.replace(f"/{stake}", "")
    if asset not in ranks.columns:
      dataframe["rel_momentum_rank"] = float("nan")
      dataframe["exit_cond_rotation"] = False
      return dataframe

    rank_series = ranks[asset]
    dataframe["rel_momentum_rank"] = rank_series

    top_n = int(self.top_n.value)
    confirm = int(self.confirm_bars.value)
    exit_k = int(self.exit_rank_k.value)
    if exit_k < top_n:
      exit_k = top_n

    dataframe["exit_cond_rotation"] = rotation_exit_mask(rank_series, exit_rank_k=exit_k)
    dataframe["rel_momentum_entry"] = rotation_entry_mask_daily(
      rank_series,
      dataframe["date"],
      top_n=top_n,
      confirm_days=confirm,
    )
    return dataframe

  def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    not_bear = dataframe["btc_market_regime"] != MarketRegime.BEAR.value
    entry = dataframe.get("rel_momentum_entry", False) & not_bear
    dataframe.loc[entry, "enter_long"] = 1
    dataframe.loc[entry, "enter_tag"] = REL_MOMENTUM_ENTER_TAG
    return dataframe

  def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    return dataframe

  def custom_exit(
    self,
    pair: str,
    trade: Trade,
    current_time: datetime,
    current_rate: float,
    current_profit: float,
    **kwargs: Any,
  ) -> str | None:
    if trade.enter_tag != REL_MOMENTUM_ENTER_TAG or self.dp is None:
      return None

    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    if dataframe is None or dataframe.empty:
      return None

    exit_raw = column_value_at_time(
      dataframe, "exit_cond_rotation", current_time, self.timeframe
    )
    if exit_raw:
      return REL_MOMENTUM_EXIT_TAG
    return None
