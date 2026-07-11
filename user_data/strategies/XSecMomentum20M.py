"""
XSecMomentum20M — configuración PRIMARIA pre-registrada (filtro liquidez dinámico 20M).

Subclase de XSecMomentum (#10 control sin filtro). Activa exclusivamente el filtro de
liquidez causal definido en ``research/r2_liquidity_filter.py``:

  elegible en t ⟺ media(vol_quote, 30d).shift(1) > 20M USDT

Par no elegible → excluido del ranking (NaN). Par en cartera que pierde elegibilidad
en rebalanceo → ``custom_exit`` (equivalente a desaparecer del top en pandas).

Umbral y ventana: constantes de clase, NO hyperoptimizables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pandas import DataFrame
from freqtrade.strategy import Trade

from quant_core import MarketRegime, column_value_at_time
from xsec_momentum_core import (
  LIQUIDITY_MIN_PERIODS,
  LIQUIDITY_THRESHOLD_USDT,
  LIQUIDITY_WINDOW,
  XSEC_ENTER_TAG,
  XSEC_EXIT_BEAR_TAG,
  XSEC_EXIT_LIQUIDITY_TAG,
  XSEC_EXIT_ROTATION_TAG,
  XSEC_UNIVERSE_ASSETS,
  bear_flat_on_rebalance,
  build_pair_ranks,
  liquidity_eligibility_mask,
  liquidity_exit_on_rebalance,
  quote_volume_usdt,
  rebalance_entry_mask,
  rotation_exit_on_rebalance,
  universe_close_column,
  universe_quote_volume_column,
)
from XSecMomentum import XSecMomentum


class XSecMomentum20M(XSecMomentum):
  """XSecMomentum + filtro liquidez dinámico 20M (pre-registro validación primaria)."""

  # Congelado — no optimizable (misma semántica que research #13)
  LIQUIDITY_WINDOW = LIQUIDITY_WINDOW
  LIQUIDITY_THRESHOLD = LIQUIDITY_THRESHOLD_USDT
  LIQUIDITY_MIN_PERIODS = LIQUIDITY_MIN_PERIODS

  def _active_universe_assets(self) -> tuple[str, ...]:
    """Universo operativo: whitelist del config (fixtures) o E2 fijo."""
    stake = str(self.config.get("stake_currency", "USDT"))
    wl = list(self.config.get("exchange", {}).get("pair_whitelist") or [])
    assets: list[str] = []
    for pair in wl:
      if "/" not in pair:
        continue
      asset = pair.split("/")[0]
      if asset in assets:
        continue
      assets.append(asset)
    return tuple(assets) if assets else XSEC_UNIVERSE_ASSETS

  def _merge_universe_1d_liquidity(
    self, dataframe: DataFrame, metadata: dict
  ) -> tuple[DataFrame, dict[str, str], dict[str, str]]:
    """Merge universo 1d con columnas de cierre y volumen quote USDT por activo."""
    asset_columns: dict[str, str] = {}
    quote_columns: dict[str, str] = {}
    if self.dp is None:
      return dataframe, asset_columns, quote_columns

    stake = self.config["stake_currency"]
    current_pair = metadata["pair"]
    current_asset = current_pair.split("/")[0]

    for asset in self._active_universe_assets():
      pair = f"{asset}/{stake}"
      close_col = universe_close_column(asset) if pair != current_pair else "close"
      q_col = universe_quote_volume_column(asset)

      if pair == current_pair:
        asset_columns[asset] = "close"
        dataframe[q_col] = quote_volume_usdt(dataframe["volume"], dataframe["close"])
        quote_columns[asset] = q_col
        continue

      informative = self.dp.get_pair_dataframe(pair=pair, timeframe="1d")
      if informative is None or informative.empty:
        continue
      slim = informative[["date", "close", "volume"]].copy()
      slim = slim.rename(columns={"close": close_col})
      slim[q_col] = quote_volume_usdt(slim["volume"], slim[close_col])
      dataframe = dataframe.merge(slim[["date", close_col, q_col]], on="date", how="left")
      dataframe[close_col] = dataframe[close_col].ffill()
      dataframe[q_col] = dataframe[q_col].ffill()
      asset_columns[asset] = close_col
      quote_columns[asset] = q_col

    if current_asset in self._active_universe_assets():
      asset_columns.setdefault(current_asset, "close")
      quote_columns.setdefault(current_asset, universe_quote_volume_column(current_asset))
    return dataframe, asset_columns, quote_columns

  def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = self._merge_btc_regime_1d(dataframe)
    dataframe, asset_columns, quote_columns = self._merge_universe_1d_liquidity(
      dataframe, metadata
    )

    window = int(self.momentum_window.value)
    eligibility: dict[str, Any] = {}
    for asset, q_col in quote_columns.items():
      if q_col in dataframe.columns:
        eligibility[asset] = liquidity_eligibility_mask(
          dataframe[q_col],
          window=self.LIQUIDITY_WINDOW,
          threshold=self.LIQUIDITY_THRESHOLD,
          min_periods=self.LIQUIDITY_MIN_PERIODS,
        )

    ranks = build_pair_ranks(
      dataframe,
      asset_columns=asset_columns,
      window=window,
      asset_eligibility=eligibility or None,
    )
    if ranks.empty:
      dataframe["xsec_rank"] = float("nan")
      dataframe["xsec_entry"] = False
      dataframe["exit_cond_rotation"] = False
      dataframe["exit_cond_bear_flat"] = False
      dataframe["exit_cond_liquidity"] = False
      dataframe["xsec_liquidity_eligible"] = False
      return dataframe

    pair = metadata["pair"]
    stake = self.config["stake_currency"]
    asset = pair.split("/")[0] if "/" in pair else pair.replace(f"/{stake}", "")
    if asset not in ranks.columns:
      dataframe["xsec_rank"] = float("nan")
      dataframe["xsec_entry"] = False
      dataframe["exit_cond_rotation"] = False
      dataframe["exit_cond_bear_flat"] = False
      dataframe["exit_cond_liquidity"] = False
      dataframe["xsec_liquidity_eligible"] = False
      return dataframe

    rank_series = ranks[asset]
    top_n = int(self.top_n.value)
    exit_k = int(self.exit_rank_k.value)
    if exit_k < top_n:
      exit_k = top_n

    asset_eligible = eligibility.get(asset)
    if asset_eligible is not None:
      dataframe["xsec_liquidity_eligible"] = asset_eligible
      dataframe["exit_cond_liquidity"] = liquidity_exit_on_rebalance(
        asset_eligible, dataframe["date"]
      )
    else:
      dataframe["xsec_liquidity_eligible"] = False
      dataframe["exit_cond_liquidity"] = False

    dataframe["xsec_rank"] = rank_series
    dataframe["xsec_entry"] = rebalance_entry_mask(
      rank_series, dataframe["date"], top_n=top_n
    )
    dataframe["exit_cond_rotation"] = rotation_exit_on_rebalance(
      rank_series, dataframe["date"], exit_rank_k=exit_k
    )
    dataframe["exit_cond_bear_flat"] = bear_flat_on_rebalance(
      dataframe["btc_market_regime"],
      dataframe["date"],
      bear_value=MarketRegime.BEAR.value,
    )
    return dataframe

  def confirm_trade_entry(
    self,
    pair: str,
    order_type: str,
    amount: float,
    rate: float,
    time_in_force: str,
    current_time: datetime,
    entry_tag: str | None,
    side: str,
    **kwargs: Any,
  ) -> bool:
    if not super().confirm_trade_entry(
      pair,
      order_type,
      amount,
      rate,
      time_in_force,
      current_time,
      entry_tag,
      side,
      **kwargs,
    ):
      return False
    if entry_tag != XSEC_ENTER_TAG or self.dp is None:
      return True
    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    if dataframe is None or dataframe.empty:
      return False
    eligible = column_value_at_time(
      dataframe, "xsec_liquidity_eligible", current_time, self.timeframe
    )
    return bool(eligible)

  def custom_exit(
    self,
    pair: str,
    trade: Trade,
    current_time: datetime,
    current_rate: float,
    current_profit: float,
    **kwargs: Any,
  ) -> str | None:
    if trade.enter_tag != XSEC_ENTER_TAG or self.dp is None:
      return None

    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    if dataframe is None or dataframe.empty:
      return None

    if column_value_at_time(dataframe, "exit_cond_liquidity", current_time, self.timeframe):
      return XSEC_EXIT_LIQUIDITY_TAG
    if column_value_at_time(dataframe, "exit_cond_bear_flat", current_time, self.timeframe):
      return XSEC_EXIT_BEAR_TAG
    if column_value_at_time(dataframe, "exit_cond_rotation", current_time, self.timeframe):
      return XSEC_EXIT_ROTATION_TAG
    return None
