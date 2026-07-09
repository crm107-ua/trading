"""
BreakoutVol — ruptura de rango con confirmación de volumen (1h).

Tesis: en régimen BULL (BTC), un cierre por encima del máximo de las N velas
previas con volumen elevado captura expansión de volatilidad direccional.

Entrada (modelo pesimista): señal en el cierre de la vela de ruptura; Freqtrade
no tiene stop-limit de entrada nativo — el backtest ejecuta en la apertura de la
vela siguiente (gap post-ruptura incluido, sin asumir fill en el nivel roto).

Salida: invalidación por cierre de nuevo dentro del rango (por debajo de range_high).
Stop secundario vía custom_stoploss ATR de QuantBaseStrategy.

Indicadores: range_high y volume_mean_prior usan shift(1) — la vela actual no
participa en su propio umbral (ver quant_core.compute_prior_rolling_*).
"""

from __future__ import annotations

from pandas import DataFrame
from freqtrade.strategy import IntParameter

from quant_core import (
  MarketRegime,
  compute_prior_rolling_max,
  compute_prior_rolling_mean,
)
from _base import QuantBaseStrategy


class BreakoutVol(QuantBaseStrategy):
  """Donchian superior + volumen en régimen BULL."""

  timeframe = "1h"
  can_short = False

  minimal_roi = {"0": 100}
  use_exit_signal = True

  # 3 parámetros optimizables
  buy_breakout_period = IntParameter(15, 40, default=20, space="buy", optimize=True)
  buy_volume_period = IntParameter(15, 30, default=20, space="buy", optimize=True)
  buy_volume_factor = IntParameter(10, 30, default=15, space="buy", optimize=True)

  def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = super().populate_indicators(dataframe, metadata)
    breakout_n = int(self.buy_breakout_period.value)
    volume_n = int(self.buy_volume_period.value)
    dataframe["range_high"] = compute_prior_rolling_max(dataframe["high"], breakout_n)
    dataframe["volume_mean_prior"] = compute_prior_rolling_mean(dataframe["volume"], volume_n)
    return dataframe

  def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    vol_mult = int(self.buy_volume_factor.value) / 10.0
    vol_threshold = dataframe["volume_mean_prior"] * vol_mult

    if "btc_market_regime" in dataframe.columns:
      bull_mask = dataframe["btc_market_regime"] == MarketRegime.BULL.value
    else:
      bull_mask = False

    dataframe.loc[
      (
        bull_mask
        & (dataframe["close"] > dataframe["range_high"])
        & (dataframe["volume"] > vol_threshold)
        & dataframe["range_high"].notna()
        & dataframe["volume_mean_prior"].notna()
        & (dataframe["volume_mean_prior"] > 0)
        & (dataframe["volume"] > 0)
      ),
      "enter_long",
    ] = 1
    return dataframe

  def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    # Invalidación: cierre vuelve dentro del rango roto (por debajo del máximo previo)
    dataframe.loc[
      (
        (dataframe["close"] < dataframe["range_high"])
        & dataframe["range_high"].notna()
        & (dataframe["volume"] > 0)
      ),
      "exit_long",
    ] = 1
    return dataframe
