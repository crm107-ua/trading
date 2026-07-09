"""
TrendRider — seguimiento de tendencia en spot (timeframe 1h).

Tesis: en mercados alcistas (régimen BULL en BTC), los cruces de EMA rápida/lenta
con ADX elevado capturan momentum persistente. La salida la gestiona el trailing
ATR de QuantBaseStrategy (sin ROI table).

Régimen objetivo: BULL. Evitar operar en BEAR (filtro estructural vía btc_market_regime).
"""

from __future__ import annotations

from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IntParameter

from quant_core import trend_rider_entry_mask
from _base import QuantBaseStrategy


class TrendRider(QuantBaseStrategy):
  """Cruce EMA + ADX con filtro de régimen BULL."""

  timeframe = "1h"
  can_short = False

  minimal_roi = {"0": 100}
  use_exit_signal = False

  # 5 parámetros optimizables (acotados, anti-overfitting)
  buy_ema_fast = IntParameter(8, 18, default=12, space="buy", optimize=True)
  buy_ema_slow = IntParameter(22, 40, default=26, space="buy", optimize=True)
  buy_adx = IntParameter(20, 35, default=25, space="buy", optimize=True)
  buy_volume_factor = IntParameter(10, 30, default=15, space="buy", optimize=True)
  buy_rsi_max = IntParameter(65, 80, default=72, space="buy", optimize=True)

  def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = super().populate_indicators(dataframe, metadata)
    dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=int(self.buy_ema_fast.value))
    dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=int(self.buy_ema_slow.value))
    dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
    dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
    dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()
    return dataframe

  def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    entry = trend_rider_entry_mask(
      dataframe,
      adx_threshold=int(self.buy_adx.value),
      rsi_max=int(self.buy_rsi_max.value),
      volume_factor=int(self.buy_volume_factor.value) / 10.0,
    )
    dataframe.loc[entry, "enter_long"] = 1
    return dataframe

  def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    return dataframe
