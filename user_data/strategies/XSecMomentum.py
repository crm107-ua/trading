"""
XSecMomentum — rotación cross-sectional 1d top-N (intento #10 / P1).

Motor alineado con research E2. Hereda IStrategy (no QuantBaseStrategy): Freqtrade
exige informative TF >= strategy TF; la base fija BTC@4h y no es compatible con 1d nativo.
Régimen BEAR: misma fórmula ``add_regime_indicators`` sobre BTC 1d (desviación documentada).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pandas import DataFrame
from freqtrade.strategy import IStrategy, IntParameter, Trade

from quant_core import MarketRegime, column_value_at_time, evaluate_min_stake_policy
from _base import QuantBaseStrategy
from xsec_momentum_core import (
  XSEC_ENTER_TAG,
  XSEC_EXIT_BEAR_TAG,
  XSEC_EXIT_ROTATION_TAG,
  XSEC_UNIVERSE_ASSETS,
  bear_flat_on_rebalance,
  build_pair_ranks,
  rebalance_entry_mask,
  rotation_exit_on_rebalance,
  universe_close_column,
)


class XSecMomentum(IStrategy):
  INTERFACE_VERSION = 3

  timeframe = "1d"
  can_short = False
  process_only_new_candles = True

  minimal_roi = {"0": 100}
  use_exit_signal = True
  use_custom_stoploss = False
  stoploss = -0.35

  momentum_window = IntParameter(7, 30, default=14, space="buy", optimize=True)
  top_n = IntParameter(2, 4, default=3, space="buy", optimize=True)
  exit_rank_k = IntParameter(3, 6, default=4, space="buy", optimize=True)

  startup_candle_count = 220

  def bot_start(self, **kwargs: Any) -> None:
    self._stake_reject_reason: str | None = None

  def informative_pairs(self) -> list[tuple[str, str]]:
    return []

  def _merge_btc_regime_1d(self, dataframe: DataFrame) -> DataFrame:
    if self.dp is None:
      dataframe["btc_market_regime"] = MarketRegime.RANGE.value
      return dataframe
    stake = self.config["stake_currency"]
    btc = self.dp.get_pair_dataframe(pair=f"BTC/{stake}", timeframe="1d")
    if btc is None or btc.empty:
      dataframe["btc_market_regime"] = MarketRegime.RANGE.value
      return dataframe
    reg = QuantBaseStrategy.add_regime_indicators(btc.copy())
    slim = reg[["date", "market_regime"]].rename(columns={"market_regime": "btc_market_regime"})
    out = dataframe.merge(slim, on="date", how="left")
    out["btc_market_regime"] = out["btc_market_regime"].ffill().fillna(MarketRegime.RANGE.value)
    return out

  def _merge_universe_1d(
    self, dataframe: DataFrame, metadata: dict
  ) -> tuple[DataFrame, dict[str, str]]:
    asset_columns: dict[str, str] = {}
    if self.dp is None:
      return dataframe, asset_columns

    stake = self.config["stake_currency"]
    current_pair = metadata["pair"]
    current_asset = current_pair.split("/")[0]

    for asset in XSEC_UNIVERSE_ASSETS:
      pair = f"{asset}/{stake}"
      if pair == current_pair:
        asset_columns[asset] = "close"
        continue
      informative = self.dp.get_pair_dataframe(pair=pair, timeframe="1d")
      if informative is None or informative.empty:
        continue
      col = universe_close_column(asset)
      slim = informative[["date", "close"]].rename(columns={"close": col})
      dataframe = dataframe.merge(slim, on="date", how="left")
      dataframe[col] = dataframe[col].ffill()
      asset_columns[asset] = col
    if current_asset in XSEC_UNIVERSE_ASSETS:
      asset_columns.setdefault(current_asset, "close")
    return dataframe, asset_columns

  def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = self._merge_btc_regime_1d(dataframe)
    dataframe, asset_columns = self._merge_universe_1d(dataframe, metadata)

    window = int(self.momentum_window.value)
    ranks = build_pair_ranks(dataframe, asset_columns=asset_columns, window=window)
    if ranks.empty:
      dataframe["xsec_rank"] = float("nan")
      dataframe["xsec_entry"] = False
      dataframe["exit_cond_rotation"] = False
      dataframe["exit_cond_bear_flat"] = False
      return dataframe

    pair = metadata["pair"]
    stake = self.config["stake_currency"]
    asset = pair.split("/")[0] if "/" in pair else pair.replace(f"/{stake}", "")
    if asset not in ranks.columns:
      dataframe["xsec_rank"] = float("nan")
      dataframe["xsec_entry"] = False
      dataframe["exit_cond_rotation"] = False
      dataframe["exit_cond_bear_flat"] = False
      return dataframe

    rank_series = ranks[asset]
    top_n = int(self.top_n.value)
    exit_k = int(self.exit_rank_k.value)
    if exit_k < top_n:
      exit_k = top_n

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

  def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    not_bear = dataframe["btc_market_regime"] != MarketRegime.BEAR.value
    entry = dataframe.get("xsec_entry", False) & not_bear
    dataframe.loc[entry, "enter_long"] = 1
    dataframe.loc[entry, "enter_tag"] = XSEC_ENTER_TAG
    return dataframe

  def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    return dataframe

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
    if entry_tag != XSEC_ENTER_TAG or not self.wallets:
      return proposed_stake

    top_n = max(1, int(self.top_n.value))
    wallet_balance = float(self.wallets.get_total_stake_amount())
    raw_stake = wallet_balance / float(top_n)
    stake, allowed, reason = evaluate_min_stake_policy(
      raw_stake,
      min_stake,
      policy="reject",
    )
    if not allowed:
      self._stake_reject_reason = reason
      return proposed_stake
    final_stake = stake if stake is not None else proposed_stake
    if max_stake is not None and final_stake > max_stake:
      final_stake = max_stake
    self._stake_reject_reason = None
    return final_stake

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
    if getattr(self, "_stake_reject_reason", None):
      return False
    if entry_tag != XSEC_ENTER_TAG:
      return True
    if self.dp is None:
      return True
    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    if dataframe is None or dataframe.empty:
      return False
    regime = column_value_at_time(dataframe, "btc_market_regime", current_time, self.timeframe)
    return regime != MarketRegime.BEAR.value

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

    if column_value_at_time(dataframe, "exit_cond_bear_flat", current_time, self.timeframe):
      return XSEC_EXIT_BEAR_TAG
    if column_value_at_time(dataframe, "exit_cond_rotation", current_time, self.timeframe):
      return XSEC_EXIT_ROTATION_TAG
    return None
