"""
Loss custom Fase 4 — Sharpe con penalización por drawdown y mínimo de trades.

El grid u otros mecanismos compiten en la loss; no se fuerza su uso.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from pandas import DataFrame

from freqtrade.data.metrics import calculate_max_drawdown, calculate_sharpe
from freqtrade.optimize.hyperopt import IHyperOptLoss

MIN_TRADES_DEFAULT = 100
DD_WEIGHT = 2.0
INSUFFICIENT_TRADES_LOSS = 10_000.0


def _min_trades_threshold() -> int:
  """Alineado con ``--min-trades`` del CLI vía env (orquestador)."""
  import os

  raw = os.environ.get("QUANT_ROBUST_MIN_TRADES", "").strip()
  if raw:
    return max(1, int(raw))
  return MIN_TRADES_DEFAULT


class QuantRobustLoss(IHyperOptLoss):
  @staticmethod
  def hyperopt_loss_function(
    results: DataFrame,
    trade_count: int,
    min_date: datetime,
    max_date: datetime,
    starting_balance: float,
    *args,
    **kwargs,
  ) -> float:
    if trade_count < _min_trades_threshold():
      return INSUFFICIENT_TRADES_LOSS

    sharpe = calculate_sharpe(results, min_date, max_date, starting_balance)
    if sharpe is None or np.isnan(sharpe):
      sharpe = -2.0

    try:
      md = calculate_max_drawdown(results, value_col="profit_abs")
      dd_ratio = md.drawdown_abs / max(starting_balance, 1e-9)
    except ValueError:
      dd_ratio = 0.0

    return float(-sharpe + DD_WEIGHT * dd_ratio)
