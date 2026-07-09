"""
GridDCAFixture — subclase solo para CI (ciclo DCA→stop en fixtures).

Stop fijo amplio y sin protecciones. Fuerza entrada en la vela ancla del fixture
BTC (2024-01-22 10:00 UTC) alineada con inject_grid_dca_drawdown.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from pandas import DataFrame
from freqtrade.strategy import Trade

from GridDCA import GridDCA

GRID_DCA_FIXTURE_ENTRY = pd.Timestamp("2024-01-22 10:00:00", tz="UTC")


class GridDCAFixture(GridDCA):
  """Ejercita adjust_trade_position + stop en backtests de fixture."""

  regime_filter_enabled = False

  @property
  def protections(self) -> list[dict]:
    return []

  def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = super().populate_entry_trend(dataframe, metadata)
    if metadata.get("pair") == "BTC/USDT":
      dates = pd.to_datetime(dataframe["date"], utc=True)
      dataframe.loc[dates == GRID_DCA_FIXTURE_ENTRY, "enter_long"] = 1
    return dataframe

  def custom_stoploss(
    self,
    pair: str,
    trade: Trade,
    current_time: datetime,
    current_rate: float,
    current_profit: float,
    after_fill: bool,
    **kwargs: Any,
  ) -> float:
    """Stop fijo amplio en CI — sin trailing que corte el ciclo DCA antes de 3 capas."""
    _ = (pair, trade, current_time, current_rate, current_profit, after_fill, kwargs)
    return -0.22
