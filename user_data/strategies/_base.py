"""
Clase base compartida para estrategias del laboratorio cuantitativo.

Centraliza filtro de régimen BTC, gestión de riesgo por trade (ATR stop +
stake sizing) y validaciones de entrada.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import numpy as np
import talib.abstract as ta
from pandas import DataFrame
import pandas as pd
from freqtrade.enums import RunMode
from freqtrade.strategy import IStrategy, Trade, informative, stoploss_from_open

from quant_core import (
  BREAKEVEN_PROFIT_THRESHOLD,
  DEFAULT_ADX_TREND_THRESHOLD,
  DEFAULT_ATR_PERIOD,
  DEFAULT_ATR_STOP_MULTIPLIER,
  DEFAULT_ATR_TRAIL_MULTIPLIER,
  DEFAULT_MAX_SPREAD_RATIO,
  DEFAULT_RISK_PER_TRADE,
  TRAILING_PROFIT_THRESHOLD,
  MarketRegime,
  compute_atr_stoploss_ratio,
  compute_market_regime,
  compute_raw_risk_stake_amount,
  evaluate_entry_confirmation,
  evaluate_min_stake_policy,
  evaluate_correlation_entry,
  extract_daily_returns,
  count_high_correlations,
  compute_startup_candle_count,
  column_value_at_time,
  resolve_informative_column,
)

logger = logging.getLogger(__name__)

BTC_INFORMATIVE_TIMEFRAMES = ("4h",)


class QuantBaseStrategy(IStrategy, ABC):
  """
  Estrategia abstracta con utilidades compartidas de régimen, riesgo y entrada.

  Las subclases deben implementar populate_entry_trend / populate_exit_trend.
  """

  INTERFACE_VERSION = 3

  use_custom_stoploss = True
  stoploss = -0.10
  risk_per_trade = DEFAULT_RISK_PER_TRADE
  atr_period = DEFAULT_ATR_PERIOD
  atr_stop_multiplier = DEFAULT_ATR_STOP_MULTIPLIER
  atr_trail_multiplier = DEFAULT_ATR_TRAIL_MULTIPLIER
  adx_trend_threshold = DEFAULT_ADX_TREND_THRESHOLD

  max_spread_ratio = DEFAULT_MAX_SPREAD_RATIO
  regime_filter_enabled = True
  spread_check_enabled = True
  block_bear_longs = True
  block_bull_shorts = True

  # Si el stake por riesgo 1% < min_stake del exchange: "reject" (default) o "bump_to_min"
  min_stake_policy: str = "reject"

  # Filtro de correlación entre posiciones (activar en estrategias mean-rev)
  correlation_filter_enabled: bool = False
  correlation_threshold: float = 0.8
  correlation_lookback_days: int = 30
  max_correlated_open_positions: int = 2
  # allow: opera si no hay histórico; reject: bloquea por precaución
  correlation_insufficient_policy: str = "allow"

  # Placeholder: conectar feed de noticias/calendario económico en fases futuras.
  # Activar manualmente o vía webhook externo antes de eventos de alto impacto.
  high_volatility_event: bool = False

  # Timeframe BTC para régimen: 4h evita lookahead al fusionar con pares 1h/15m
  btc_regime_timeframe = "4h"

  process_only_new_candles = True
  # Sobrescribir en subclases con compute_startup_candle_count(timeframe) si difiere de 1h
  startup_candle_count = compute_startup_candle_count("1h")

  def bot_start(self, **kwargs: Any) -> None:
    self._stake_reject_reason: str | None = None

  @property
  def protections(self) -> list[dict]:
    return [
      {
        "method": "StoplossGuard",
        "lookback_period_candles": 48,
        "trade_limit": 4,
        "stop_duration_candles": 24,
        "only_per_pair": False,
      },
      {
        "method": "MaxDrawdown",
        "lookback_period_candles": 168,
        "trade_limit": 20,
        "stop_duration_candles": 48,
        "max_allowed_drawdown": 0.10,
      },
      {
        "method": "CooldownPeriod",
        "stop_duration_candles": 2,
      },
      {
        "method": "LowProfitPairs",
        "lookback_period_candles": 144,
        "trade_limit": 4,
        "stop_duration_candles": 60,
        "required_profit": 0.02,
      },
    ]

  def informative_pairs(self) -> list[tuple[str, str]]:
    stake = self.config["stake_currency"]
    pair = f"BTC/{stake}"
    return [(pair, tf) for tf in BTC_INFORMATIVE_TIMEFRAMES]

  @informative("4h", asset="BTC/USDT")
  def populate_indicators_btc_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    """Régimen BTC en 4h — el decorador @informative evita lookahead al fusionar."""
    return self.add_regime_indicators(dataframe, self.adx_trend_threshold)

  def _attach_btc_regime_columns(self, dataframe: DataFrame) -> None:
    if "btc_market_regime" in dataframe.columns:
      return
    regime_col = resolve_informative_column(
      dataframe.columns, "market_regime", timeframe_suffix="4h", required=True
    )
    dataframe["btc_market_regime"] = dataframe[regime_col]
    ema_col = resolve_informative_column(
      dataframe.columns, "ema200", timeframe_suffix="4h", required=False
    )
    if ema_col is not None:
      dataframe["btc_ema200"] = dataframe[ema_col]
    adx_col = resolve_informative_column(
      dataframe.columns, "adx", timeframe_suffix="4h", required=False
    )
    if adx_col is not None:
      dataframe["btc_adx"] = dataframe[adx_col]

  @staticmethod
  def add_regime_indicators(dataframe: DataFrame, adx_threshold: float = DEFAULT_ADX_TREND_THRESHOLD) -> DataFrame:
    """Indicadores de régimen — solo operaciones rolling/causales (sin stats globales)."""
    dataframe = dataframe.copy()
    dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
    dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

    valid = dataframe["ema200"].notna() & dataframe["adx"].notna()
    close = dataframe["close"]
    ema200 = dataframe["ema200"]
    adx = dataframe["adx"]

    regime = np.where(
      ~valid,
      MarketRegime.RANGE.value,
      np.where(
        adx < adx_threshold,
        MarketRegime.RANGE.value,
        np.where(close > ema200, MarketRegime.BULL.value, MarketRegime.BEAR.value),
      ),
    )
    dataframe["market_regime"] = regime
    return dataframe

  def market_regime(self, dataframe: DataFrame, current_time: datetime | None = None) -> MarketRegime:
    if dataframe.empty or "market_regime" not in dataframe.columns:
      return MarketRegime.RANGE
    try:
      if current_time is not None:
        label = column_value_at_time(dataframe, "market_regime", current_time, self.timeframe)
      else:
        label = dataframe["market_regime"].iloc[-1]
      if label is None:
        return MarketRegime.RANGE
      return MarketRegime(label)
    except ValueError:
      return MarketRegime.RANGE

  def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period)
    self._attach_btc_regime_columns(dataframe)
    return dataframe

  def _atr_at_time(self, pair: str, current_time: datetime) -> float | None:
    """ATR causal en current_time — no leer iloc[-1] del dataframe completo."""
    if self.dp is None:
      return None
    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    raw = column_value_at_time(dataframe, "atr", current_time, self.timeframe)
    if raw is None:
      return None
    atr = float(raw)
    if atr != atr or atr <= 0:
      return None
    return atr

  def _current_btc_regime(
    self, pair: str | None = None, current_time: datetime | None = None
  ) -> MarketRegime:
    """
    Régimen BTC sin lookahead: columna fusionada del par operado en current_time.
    No leer BTC/4h crudo — esa serie no tiene el desplazamiento del @informative.
    """
    if self.dp is None:
      return MarketRegime.RANGE

    if pair and current_time is not None:
      dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
      if dataframe is not None and not dataframe.empty and "btc_market_regime" in dataframe.columns:
        label = column_value_at_time(
          dataframe, "btc_market_regime", current_time, self.timeframe
        )
        if label is not None:
          try:
            return MarketRegime(label)
          except ValueError:
            return MarketRegime.RANGE

    if current_time is None:
      return MarketRegime.RANGE

    stake = self.config["stake_currency"]
    btc_pair = f"BTC/{stake}"
    dataframe, _ = self.dp.get_analyzed_dataframe(btc_pair, self.btc_regime_timeframe)
    if dataframe is None or dataframe.empty:
      return MarketRegime.RANGE
    if "market_regime_4h" in dataframe.columns:
      label = column_value_at_time(
        dataframe, "market_regime_4h", current_time, self.btc_regime_timeframe
      )
    elif "market_regime" in dataframe.columns:
      label = column_value_at_time(
        dataframe, "market_regime", current_time, self.btc_regime_timeframe
      )
    else:
      return MarketRegime.RANGE
    if label is None:
      return MarketRegime.RANGE
    try:
      return MarketRegime(label)
    except ValueError:
      return MarketRegime.RANGE

  def _is_spread_check_active(self) -> bool:
    """
    El spread solo es medible con orderbook (dry-run / live).
    En backtest y hyperopt se desactiva explícitamente para evitar discrepancias.
    """
    if not self.spread_check_enabled:
      return False
    if self.dp is None:
      return False
    return self.dp.runmode in (RunMode.LIVE, RunMode.DRY_RUN)

  def _current_spread_ratio(self, pair: str) -> float | None:
    if not self._is_spread_check_active():
      return None
    try:
      ob = self.dp.orderbook(pair, 1)
      if not ob or not ob.get("bids") or not ob.get("asks"):
        return None
      best_bid = ob["bids"][0][0]
      best_ask = ob["asks"][0][0]
      if best_bid <= 0:
        return None
      return (best_ask - best_bid) / best_bid
    except Exception:
      return None

  def _pair_close_series(self, pair: str, current_time: datetime | None = None) -> Any:
    """Obtiene cierres del par desde el dataprovider (backtest/live)."""
    if self.dp is None:
      return None
    tf = self.timeframe
    try:
      df = self.dp.get_pair_dataframe(pair=pair, timeframe=tf)
    except Exception:
      return None
    if df is None or df.empty or "close" not in df.columns:
      return None
    if "date" in df.columns:
      series = df.set_index("date")["close"]
    else:
      series = df["close"]
    if current_time is not None:
      ct = pd.Timestamp(current_time)
      if ct.tzinfo is None and series.index.tz is not None:
        ct = ct.tz_localize("UTC")
      series = series[series.index <= ct]
    return series

  def _open_trade_pairs(self) -> list[str]:
    try:
      from freqtrade.persistence import Trade

      open_trades = Trade.get_trades_proxy(is_open=True)
      return [t.pair for t in open_trades if t.pair]
    except Exception:
      return []

  def _correlation_entry_check(self, pair: str, current_time: datetime | None = None) -> tuple[bool, str]:
    if not self.correlation_filter_enabled:
      return True, "ok"

    candidate_closes = self._pair_close_series(pair, current_time)
    if candidate_closes is None or len(candidate_closes) < 10:
      allowed, reason = evaluate_correlation_entry(
        0,
        self.max_correlated_open_positions,
        [pair],
        insufficient_policy=self.correlation_insufficient_policy,
      )
      if not allowed:
        logger.warning(
          "%s: correlación — historial candidato insuficiente, política=%s → rechazo",
          pair,
          self.correlation_insufficient_policy,
        )
      else:
        logger.warning(
          "%s: correlación — historial candidato insuficiente, política=%s → permitir",
          pair,
          self.correlation_insufficient_policy,
        )
      return allowed, reason

    candidate_returns = extract_daily_returns(
      candidate_closes, self.correlation_lookback_days
    )
    open_pairs = [p for p in self._open_trade_pairs() if p != pair]
    open_returns: dict[str, Any] = {}
    insufficient: list[str] = []
    for open_pair in open_pairs:
      closes = self._pair_close_series(open_pair, current_time)
      if closes is None or len(closes) < 10:
        insufficient.append(open_pair)
        continue
      returns = extract_daily_returns(closes, self.correlation_lookback_days)
      if returns.empty:
        insufficient.append(open_pair)
        continue
      open_returns[open_pair] = returns

    high_count, high_detail, insuf_from_corr = count_high_correlations(
      candidate_returns,
      open_returns,
      threshold=self.correlation_threshold,
    )
    insufficient.extend(insuf_from_corr)

    allowed, reason = evaluate_correlation_entry(
      high_count,
      self.max_correlated_open_positions,
      insufficient,
      insufficient_policy=self.correlation_insufficient_policy,
    )
    if not allowed:
      detail = ", ".join(f"{p}:{c:.2f}" for p, c in high_detail[:3])
      logger.info(
        "%s: ENTRADA_RECHAZADA motivo=%s detalle=[%s] insuficientes=%s",
        pair,
        reason,
        detail,
        insufficient[:3],
      )
    elif insufficient:
      logger.warning(
        "%s: correlación — pares con histórico insuficiente %s (política=%s)",
        pair,
        insufficient[:3],
        self.correlation_insufficient_policy,
      )
    return allowed, reason

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
    atr = self._atr_at_time(pair, current_time)
    if atr is None:
      return self.stoploss

    sl = compute_atr_stoploss_ratio(
      current_profit=current_profit,
      atr=atr,
      open_rate=float(trade.open_rate),
      current_rate=current_rate,
      atr_stop_multiplier=self.atr_stop_multiplier,
      atr_trail_multiplier=self.atr_trail_multiplier,
      stoploss_from_open_fn=stoploss_from_open,
    )
    logger.debug(
      "%s: custom_stoploss profit=%.2f%% atr=%.6f sl=%.4f",
      pair,
      current_profit * 100,
      atr,
      sl,
    )
    return sl

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
    atr = self._atr_at_time(pair, current_time)
    if atr is None or not self.wallets:
      return proposed_stake

    wallet_balance = float(self.wallets.get_total_stake_amount())
    raw_stake = compute_raw_risk_stake_amount(
      wallet_balance=wallet_balance,
      atr=atr,
      rate=current_rate,
      risk_per_trade=self.risk_per_trade,
      atr_stop_multiplier=self.atr_stop_multiplier,
    )
    stake, allowed, reason = evaluate_min_stake_policy(
      raw_stake,
      min_stake,
      policy=self.min_stake_policy,
    )

    if not allowed:
      logger.warning(
        "%s: ENTRADA_RECHAZADA_POR_STAKE raw=%.2f min_stake=%s motivo=%s",
        pair,
        raw_stake,
        min_stake,
        reason,
      )
      self._stake_reject_reason = reason
      return proposed_stake

    if reason.startswith("stake_elevado_al_minimo"):
      logger.warning("%s: %s — riesgo real > %.1f%% del capital", pair, reason, self.risk_per_trade * 100)

    final_stake = stake if stake is not None else proposed_stake
    if max_stake is not None and final_stake > max_stake:
      final_stake = max_stake

    self._stake_reject_reason = None
    logger.debug(
      "%s: custom_stake wallet=%.2f raw=%.2f final=%.2f atr=%.6f",
      pair,
      wallet_balance,
      raw_stake,
      final_stake,
      atr,
    )
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
    spread = self._current_spread_ratio(pair)
    regime = (
      self._current_btc_regime(pair, current_time) if self.regime_filter_enabled else None
    )
    spread_active = self._is_spread_check_active()
    stake_reject = getattr(self, "_stake_reject_reason", None)

    allowed, reason = evaluate_entry_confirmation(
      spread_ratio=spread,
      regime=regime,
      side=side,
      max_spread_ratio=self.max_spread_ratio,
      block_bear_longs=self.block_bear_longs,
      block_bull_shorts=self.block_bull_shorts,
      high_volatility_event=self.high_volatility_event,
      regime_filter_enabled=self.regime_filter_enabled,
      spread_check_enabled=spread_active,
      stake_allowed=stake_reject is None,
      stake_reason=stake_reject or "ok",
    )

    if allowed and self.correlation_filter_enabled:
      corr_ok, corr_reason = self._correlation_entry_check(pair, current_time)
      if not corr_ok:
        allowed = False
        reason = corr_reason

    runmode = self.dp.runmode.value if self.dp else "unknown"
    if allowed:
      logger.info(
        "ENTRADA_CONFIRMADA pair=%s side=%s runmode=%s regime=%s spread=%s spread_check=%s",
        pair,
        side,
        runmode,
        regime.value if regime else "N/A",
        f"{spread:.4f}" if spread is not None else "N/A",
        spread_active,
      )
    else:
      logger.info(
        "ENTRADA_RECHAZADA pair=%s side=%s motivo=%s runmode=%s regime=%s spread=%s spread_check=%s",
        pair,
        side,
        reason,
        runmode,
        regime.value if regime else "N/A",
        f"{spread:.4f}" if spread is not None else "N/A",
        spread_active,
      )
    return allowed

  @abstractmethod
  def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    """Definir señales de entrada en subclases."""

  @abstractmethod
  def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    """Definir señales de salida en subclases."""
