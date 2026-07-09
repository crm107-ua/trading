"""
RegimeSwitcher — alterna TrendRider (BULL) y mean-rev RANGE en 1h según btc_market_regime.

La rama RANGE reimplementa lógica tipo MeanRevBB en 1h; no copia hyperopt de MeanRevBB 15m.
Salidas por enter_tag vía custom_exit (populate_exit_trend vacío). Ver docs/REGIME_SWITCHER.md.

Hyperopt (Opción A): régimen congelado (EMA200/ADX de la base). 4 params por rama.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import talib.abstract as ta
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter, IntParameter, Trade

from quant_core import (
  MEAN_REV_ENTER_TAG,
  MEAN_REV_SIGNAL_EXIT_TAG,
  TREND_ENTER_TAG,
  TREND_SIGNAL_EXIT_TAG,
  column_value_at_time,
  mean_rev_entry_mask,
  mean_rev_exit_mask,
  resolve_regime_switcher_signal_exit,
  trend_rider_entry_mask,
  trend_rider_exit_mask,
)
from _base import QuantBaseStrategy


class RegimeSwitcher(QuantBaseStrategy):
  """BULL → trend (TrendRider); RANGE → mean_rev (BB+RSI en 1h)."""

  timeframe = "1h"
  can_short = False

  minimal_roi = {"0": 100}
  # Freqtrade solo consulta custom_exit si use_exit_signal=True; populate_exit_trend vacío
  use_exit_signal = True

  correlation_filter_enabled = True
  correlation_threshold = 0.8
  correlation_lookback_days = 30
  max_correlated_open_positions = 2
  correlation_insufficient_policy = "allow"

  # Rama trend — defaults transferibles desde TrendRider (rsi_max congelado en 72)
  trend_ema_fast = IntParameter(8, 18, default=12, space="buy", optimize=True)
  trend_ema_slow = IntParameter(22, 40, default=26, space="buy", optimize=True)
  trend_adx = IntParameter(20, 35, default=25, space="buy", optimize=True)
  trend_volume_factor = IntParameter(10, 30, default=15, space="buy", optimize=True)

  # Rama range — optimizar en 1h (offsets congelados en defaults MeanRevBB)
  range_buy_rsi = IntParameter(20, 35, default=28, space="buy", optimize=True)
  range_sell_rsi = IntParameter(45, 60, default=50, space="sell", optimize=True)
  range_bb_period = IntParameter(18, 24, default=20, space="buy", optimize=True)
  range_bb_std = DecimalParameter(1.8, 2.4, default=2.0, decimals=1, space="buy", optimize=True)

  def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = super().populate_indicators(dataframe, metadata)

    dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=int(self.trend_ema_fast.value))
    dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=int(self.trend_ema_slow.value))
    dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
    dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
    dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()

    bb_period = int(self.range_bb_period.value)
    bb_std = float(self.range_bb_std.value)
    boll = ta.BBANDS(dataframe, timeperiod=bb_period, nbdevup=bb_std, nbdevdn=bb_std)
    dataframe["bb_lower"] = boll["lowerband"]
    dataframe["bb_middle"] = boll["middleband"]
    dataframe["bb_upper"] = boll["upperband"]

    dataframe["exit_cond_trend"] = trend_rider_exit_mask(dataframe)
    dataframe["exit_cond_range"] = mean_rev_exit_mask(
      dataframe,
      sell_rsi=int(self.range_sell_rsi.value),
      bb_mid_tolerance=0.005,
    )
    return dataframe

  def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    trend_entry = trend_rider_entry_mask(
      dataframe,
      adx_threshold=int(self.trend_adx.value),
      rsi_max=72,
      volume_factor=int(self.trend_volume_factor.value) / 10.0,
    )
    range_entry = mean_rev_entry_mask(
      dataframe,
      rsi_threshold=int(self.range_buy_rsi.value),
      bb_offset=0.0,
    )

    dataframe.loc[trend_entry, "enter_long"] = 1
    dataframe.loc[trend_entry, "enter_tag"] = TREND_ENTER_TAG
    dataframe.loc[range_entry, "enter_long"] = 1
    dataframe.loc[range_entry, "enter_tag"] = MEAN_REV_ENTER_TAG
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
    tag = trade.enter_tag
    if not tag or self.dp is None:
      return None

    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    if dataframe is None or dataframe.empty:
      return None

    exit_trend_raw = column_value_at_time(
      dataframe, "exit_cond_trend", current_time, self.timeframe
    )
    exit_range_raw = column_value_at_time(
      dataframe, "exit_cond_range", current_time, self.timeframe
    )
    return resolve_regime_switcher_signal_exit(
      tag,
      bool(exit_trend_raw),
      bool(exit_range_raw),
    )
