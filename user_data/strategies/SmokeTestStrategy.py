"""
SmokeTestStrategy — estrategia mínima para validar el entorno (Fase 1).

Hereda QuantBaseStrategy con filtros de régimen desactivados.
Configuración orientada a pasar lookahead-analysis (sin ROI table ni
exit_signal que introducen dependencia de ruta en el test de Freqtrade).
"""

from __future__ import annotations

from pandas import DataFrame
import talib.abstract as ta

from _base import QuantBaseStrategy


class SmokeTestStrategy(QuantBaseStrategy):
  """Cruce EMA 9/21 simple para smoke-test de backtesting."""

  timeframe = "1h"
  can_short = False

  # ROI desactivada: la tabla ROI + exit_signal generan falsos positivos en lookahead
  minimal_roi = {"0": 100}
  use_exit_signal = False

  trailing_stop = False
  regime_filter_enabled = False
  correlation_filter_enabled = False
  use_custom_stoploss = False

  @property
  def protections(self) -> list[dict]:
    return []

  def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = super().populate_indicators(dataframe, metadata)
    dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=9)
    dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=21)
    return dataframe

  def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe.loc[
      (
        (dataframe["ema_fast"] > dataframe["ema_slow"])
        & (dataframe["volume"] > 0)
      ),
      "enter_long",
    ] = 1
    return dataframe

  def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    return dataframe
