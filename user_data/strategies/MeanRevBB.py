"""
MeanRevBB — reversión a la media con Bollinger Bands (15m).

Tesis: en régimen RANGE (BTC lateral), sobreventas intradía (RSI bajo + cierre
bajo banda inferior) tienden a revertir hacia la media. Salida en banda media;
stop vía ATR de la base.

Protección de correlación: no abrir si ya hay >=2 posiciones abiertas con
correlación de retornos diarios (30d) > 0.8 respecto al par candidato.
"""

from __future__ import annotations

from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IntParameter, DecimalParameter

from quant_core import (
  compute_startup_candle_count,
  mean_rev_entry_mask,
  mean_rev_exit_mask,
)
from _base import QuantBaseStrategy


class MeanRevBB(QuantBaseStrategy):
  """RSI + Bollinger inferior en régimen RANGE con filtro de correlación."""

  timeframe = "15m"
  can_short = False
  startup_candle_count = compute_startup_candle_count("15m")

  minimal_roi = {"0": 100}
  use_exit_signal = True

  block_bear_longs = True
  block_bull_shorts = True

  correlation_filter_enabled = True
  correlation_threshold = 0.8
  correlation_lookback_days = 30
  max_correlated_open_positions = 2
  correlation_insufficient_policy = "allow"

  buy_rsi = IntParameter(20, 35, default=28, space="buy", optimize=True)
  sell_rsi = IntParameter(45, 60, default=50, space="sell", optimize=True)
  bb_period = IntParameter(18, 24, default=20, space="buy", optimize=True)
  bb_std = DecimalParameter(1.8, 2.4, default=2.0, decimals=1, space="buy", optimize=True)
  buy_bb_offset = DecimalParameter(0.0, 0.02, default=0.0, decimals=2, space="buy", optimize=True)
  sell_bb_mid_tolerance = DecimalParameter(0.0, 0.01, default=0.005, decimals=3, space="sell", optimize=True)

  def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = super().populate_indicators(dataframe, metadata)
    period = int(self.bb_period.value)
    std = float(self.bb_std.value)
    boll = ta.BBANDS(dataframe, timeperiod=period, nbdevup=std, nbdevdn=std)
    dataframe["bb_lower"] = boll["lowerband"]
    dataframe["bb_middle"] = boll["middleband"]
    dataframe["bb_upper"] = boll["upperband"]
    dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
    return dataframe

  def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    entry = mean_rev_entry_mask(
      dataframe,
      rsi_threshold=int(self.buy_rsi.value),
      bb_offset=float(self.buy_bb_offset.value),
    )
    dataframe.loc[entry, "enter_long"] = 1
    return dataframe

  def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    exit_mask = mean_rev_exit_mask(
      dataframe,
      sell_rsi=int(self.sell_rsi.value),
      bb_mid_tolerance=float(self.sell_bb_mid_tolerance.value),
    )
    dataframe.loc[exit_mask, "exit_long"] = 1
    return dataframe
