"""
RegimeSwitcherWideStop — subclase solo para tests de integración.

Stop amplio solo en trades mean_rev para que custom_exit cierre por señal antes
que el ATR. Trend mantiene custom_stoploss normal para no bloquear max_open_trades.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from freqtrade.strategy import Trade

from quant_core import MEAN_REV_ENTER_TAG
from RegimeSwitcher import RegimeSwitcher


class RegimeSwitcherWideStop(RegimeSwitcher):
  """Ejercita dispatch de custom_exit en rama mean_rev (fixtures / CI)."""

  @property
  def protections(self) -> list[dict]:
    return []

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
    if trade.enter_tag == MEAN_REV_ENTER_TAG:
      return -0.99
    return super().custom_stoploss(
      pair, trade, current_time, current_rate, current_profit, after_fill, **kwargs
    )
