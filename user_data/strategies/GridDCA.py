"""
GridDCA — DCA escalonado en spot (1h) con presupuesto máximo por posición.

Entrada inicial solo en régimen no-BEAR (BULL o RANGE). Hasta 3 compras adicionales
con tamaño decreciente si el precio cae desde la última entrada. BEAR congela ajustes;
el stop global (ATR sobre precio promediado) gobierna la salida.

Riesgo: promediar a la baja en tendencia bajista puede ser ruinoso — ver docs/GRID_DCA.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import talib.abstract as ta
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter, IntParameter, Trade

from quant_core import (
  DEFAULT_DCA_LAYER_FRACTIONS,
  DEFAULT_DCA_MAX_ADDITIONAL_ENTRIES,
  DEFAULT_GRID_MAX_POSITION_RATIO,
  MarketRegime,
  column_value_at_time,
  compute_dca_layer_stakes,
  evaluate_dca_adjustment,
  get_trade_last_entry_rate,
  regime_allows_grid_dca,
)
from _base import QuantBaseStrategy

GRID_MAX_BUDGET_KEY = "grid_max_budget"
GRID_LAYER_STAKES_KEY = "grid_layer_stakes"


class GridDCA(QuantBaseStrategy):
  """Pullback RSI + DCA en capas con tope de exposición por posición."""

  timeframe = "1h"
  can_short = False

  minimal_roi = {"0": 100}
  use_exit_signal = False

  position_adjustment_enable = True
  max_entry_position_adjustment = DEFAULT_DCA_MAX_ADDITIONAL_ENTRIES

  grid_max_position_ratio = DEFAULT_GRID_MAX_POSITION_RATIO
  dca_layer_fractions = DEFAULT_DCA_LAYER_FRACTIONS

  buy_rsi_max = IntParameter(40, 55, default=48, space="buy", optimize=True)
  dca_min_drop_pct = DecimalParameter(
    0.015, 0.04, default=0.02, decimals=3, space="buy", optimize=True
  )

  def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = super().populate_indicators(dataframe, metadata)
    dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
    return dataframe

  def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    if "btc_market_regime" not in dataframe.columns:
      return dataframe

    non_bear = dataframe["btc_market_regime"].isin(
      [MarketRegime.BULL.value, MarketRegime.RANGE.value]
    )
    dataframe.loc[
      non_bear
      & (dataframe["rsi"] < int(self.buy_rsi_max.value))
      & (dataframe["volume"] > 0),
      "enter_long",
    ] = 1
    return dataframe

  def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    return dataframe

  def _wallet_budget(self) -> float:
    if not self.wallets:
      return 0.0
    return float(self.wallets.get_total_stake_amount()) * self.grid_max_position_ratio

  def _ensure_grid_budget_metadata(self, trade: Trade) -> tuple[float, list[float]]:
    budget = trade.get_custom_data(GRID_MAX_BUDGET_KEY)
    layers_raw = trade.get_custom_data(GRID_LAYER_STAKES_KEY)
    if budget is not None and layers_raw is not None:
      return float(budget), [float(x) for x in layers_raw]

    budget = self._wallet_budget()
    layers = compute_dca_layer_stakes(budget, self.dca_layer_fractions)
    trade.set_custom_data(GRID_MAX_BUDGET_KEY, budget)
    trade.set_custom_data(GRID_LAYER_STAKES_KEY, layers)
    return budget, layers

  def custom_stake_amount(
    self,
    pair: str,
    current_time: datetime,
    current_rate: float,
    proposed_stake: float,
    min_stake: float | None,
    max_stake: float | None,
    leverage: float,
    entry_tag: str | None,
    side: str,
    **kwargs: Any,
  ) -> float:
    budget = self._wallet_budget()
    layers = compute_dca_layer_stakes(budget, self.dca_layer_fractions)
    if not layers:
      return super().custom_stake_amount(
        pair,
        current_time,
        current_rate,
        proposed_stake,
        min_stake,
        max_stake,
        leverage,
        entry_tag,
        side,
        **kwargs,
      )

    initial = layers[0]
    if min_stake is not None and initial < min_stake:
      return super().custom_stake_amount(
        pair,
        current_time,
        current_rate,
        proposed_stake,
        min_stake,
        max_stake,
        leverage,
        entry_tag,
        side,
        **kwargs,
      )

    if max_stake is not None:
      initial = min(initial, max_stake)
    return initial

  def adjust_trade_position(
    self,
    trade: Trade,
    current_time: datetime,
    current_rate: float,
    current_profit: float,
    min_stake: float | None,
    max_stake: float | None,
    current_entry_rate: float,
    current_exit_rate: float,
    current_entry_profit: float,
    current_exit_profit: float,
    **kwargs: Any,
  ) -> float | None:
    regime = self._current_btc_regime(trade.pair, current_time)
    if not regime_allows_grid_dca(regime):
      return None

    budget, layers = self._ensure_grid_budget_metadata(trade)
    layer_idx = int(trade.nr_of_successful_entries)
    if layer_idx >= len(layers):
      return None

    atr_raw = None
    if self.dp is not None:
      dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
      if dataframe is not None and not dataframe.empty:
        atr_raw = column_value_at_time(dataframe, "atr", current_time, self.timeframe)
    atr = float(atr_raw) if atr_raw is not None else None

    stake, reason = evaluate_dca_adjustment(
      successful_entries=int(trade.nr_of_successful_entries),
      max_additional_entries=self.max_entry_position_adjustment,
      current_stake=float(trade.stake_amount),
      next_layer_stake=float(layers[layer_idx]),
      max_position_budget=budget,
      reference_entry_rate=get_trade_last_entry_rate(trade),
      current_rate=float(current_rate),
      atr=atr,
      regime=regime,
      min_drop_pct=float(self.dca_min_drop_pct.value),
      min_stake=min_stake,
    )

    if stake is None:
      if reason.startswith("regimen_BEAR"):
        return None
      return None

    if max_stake is not None and stake > max_stake:
      stake = max_stake

    return stake

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
    """Stop sobre trade.open_rate — Freqtrade actualiza el promedio tras cada DCA."""
    return super().custom_stoploss(
      pair, trade, current_time, current_rate, current_profit, after_fill, **kwargs
    )
