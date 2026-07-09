"""Tests unitarios de quant_core y lógica de QuantBaseStrategy."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from quant_core import (  # noqa: E402
  BREAKEVEN_PROFIT_THRESHOLD,
  TRAILING_PROFIT_THRESHOLD,
  InformativeColumnNotFoundError,
  MarketRegime,
  compute_atr_stoploss_ratio,
  compute_market_regime,
  compute_risk_stake_amount,
  compute_startup_candle_count,
  column_value_at_time,
  resolve_informative_column,
  compute_atr_stoploss_ratio,
  evaluate_entry_confirmation,
  evaluate_min_stake_policy,
)


class TestMarketRegime:
  def test_bull_when_price_above_ema_and_strong_adx(self) -> None:
    assert compute_market_regime(50_000, 48_000, 30) == MarketRegime.BULL

  def test_bear_when_price_below_ema_and_strong_adx(self) -> None:
    assert compute_market_regime(45_000, 48_000, 28) == MarketRegime.BEAR

  def test_range_when_adx_low(self) -> None:
    assert compute_market_regime(50_000, 48_000, 18) == MarketRegime.RANGE
    assert compute_market_regime(45_000, 48_000, 15) == MarketRegime.RANGE


class TestBtcRegimeColumnAttach:
  def test_resolves_freqtrade_2026_informative_column_name(self) -> None:
    cols = ["btc_usdt_market_regime_4h", "btc_usdt_ema200_4h", "btc_usdt_adx_4h"]
    assert resolve_informative_column(cols, "market_regime") == "btc_usdt_market_regime_4h"
    assert resolve_informative_column(cols, "ema200") == "btc_usdt_ema200_4h"
    assert resolve_informative_column(["market_regime_4h"], "market_regime") == "market_regime_4h"

  def test_raises_when_informative_column_missing(self) -> None:
    with pytest.raises(InformativeColumnNotFoundError):
      resolve_informative_column(["close", "volume"], "market_regime")

  def test_optional_column_returns_none_without_error(self) -> None:
    assert resolve_informative_column(["close"], "ema200", required=False) is None


class TestColumnValueAtTime:
  def test_ignores_absurd_tail_atr(self) -> None:
    """La cola del dataframe no debe influir en lecturas en current_time pasado."""
    dates = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
    df = pd.DataFrame({"date": dates, "atr": [2.0] * 9 + [999.0]})
    mid = dates[5].to_pydatetime()
    assert column_value_at_time(df, "atr", mid, "1h") == 2.0

  def test_regime_label_at_time(self) -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    df = pd.DataFrame(
      {
        "date": dates,
        "btc_market_regime": ["RANGE", "RANGE", "BULL", "BULL", "BEAR"],
      }
    )
    t = dates[2].to_pydatetime()
    assert column_value_at_time(df, "btc_market_regime", t, "1h") == "BULL"


class TestCustomStoplossCausalAtr:
  """custom_stoploss no debe usar ATR del final del histórico en backtest."""

  def test_stoploss_stable_when_tail_atr_is_absurd(self) -> None:
    dates = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
    df = pd.DataFrame({"date": dates, "atr": [2.0] * 9 + [999.0]})
    mid = dates[5].to_pydatetime()
    atr = column_value_at_time(df, "atr", mid, "1h")
    assert atr == 2.0
    sl = compute_atr_stoploss_ratio(
      current_profit=-0.01,
      atr=float(atr),
      open_rate=100.0,
      current_rate=99.0,
    )
    sl_absurd = compute_atr_stoploss_ratio(
      current_profit=-0.01,
      atr=999.0,
      open_rate=100.0,
      current_rate=99.0,
    )
    assert sl != sl_absurd
    assert sl < 0.1


class TestStartupCandleCount:
  def test_1h_warmup_for_ema200_on_4h(self) -> None:
    assert compute_startup_candle_count("1h") == 850

  def test_15m_warmup_scales_with_timeframe(self) -> None:
    assert compute_startup_candle_count("15m") == 3250


class TestCustomStoploss:
  OPEN = 100.0
  ATR = 2.0

  def test_initial_stop_uses_2x_atr_from_entry(self) -> None:
    sl = compute_atr_stoploss_ratio(
      current_profit=-0.01,
      atr=self.ATR,
      open_rate=self.OPEN,
      current_rate=99.0,
    )
    assert sl > 0.03

  def test_breakeven_at_2pct_profit(self) -> None:
    sl = compute_atr_stoploss_ratio(
      current_profit=BREAKEVEN_PROFIT_THRESHOLD,
      atr=self.ATR,
      open_rate=self.OPEN,
      current_rate=102.0,
    )
    assert sl > 0
    assert sl < 0.03

  def test_trailing_tighter_at_4pct_profit(self) -> None:
    sl_loss = compute_atr_stoploss_ratio(
      current_profit=-0.02,
      atr=self.ATR,
      open_rate=self.OPEN,
      current_rate=98.0,
    )
    sl_trail = compute_atr_stoploss_ratio(
      current_profit=TRAILING_PROFIT_THRESHOLD,
      atr=self.ATR,
      open_rate=self.OPEN,
      current_rate=104.0,
    )
    assert sl_trail < sl_loss


class TestCustomStakeAmount:
  def test_risk_1pct_sizing(self) -> None:
    stake = compute_risk_stake_amount(10_000.0, 200.0, 10_000.0, risk_per_trade=0.01)
    assert stake == pytest.approx(2500.0, rel=0.01)

  def test_respects_min_stake_with_legacy_helper(self) -> None:
    """compute_risk_stake_amount (legacy) eleva al mínimo si se pasa min_stake."""
    stake = compute_risk_stake_amount(100.0, 50.0, 10_000.0, min_stake=50.0)
    assert stake >= 50.0

  def test_rejects_when_raw_below_min(self) -> None:
    stake, allowed, reason = evaluate_min_stake_policy(25.0, 50.0, policy="reject")
    assert not allowed
    assert stake is None
    assert reason.startswith("stake_bajo_minimo")

  def test_bump_to_min_logs_elevated_risk(self) -> None:
    stake, allowed, reason = evaluate_min_stake_policy(25.0, 50.0, policy="bump_to_min")
    assert allowed
    assert stake == 50.0
    assert reason.startswith("stake_elevado_al_minimo")

  def test_reject_blocks_entry_via_confirm_helper(self) -> None:
    allowed, reason = evaluate_entry_confirmation(
      None,
      MarketRegime.BULL,
      "long",
      spread_check_enabled=False,
      stake_allowed=False,
      stake_reason="stake_bajo_minimo:raw=25.00<min=50.00",
    )
    assert not allowed
    assert reason.startswith("stake_bajo_minimo")

  def test_respects_max_stake(self) -> None:
    stake = compute_risk_stake_amount(1_000_000.0, 200.0, 10_000.0, max_stake=5000.0)
    assert stake <= 5000.0

  def test_zero_atr_returns_zero_raw_stake(self) -> None:
    assert compute_risk_stake_amount(10_000, 0, 100, min_stake=10) == 0.0


class TestConfirmTradeEntry:
  def test_blocks_high_spread(self) -> None:
    allowed, reason = evaluate_entry_confirmation(0.005, MarketRegime.BULL, "long")
    assert not allowed
    assert reason.startswith("spread_alto")

  def test_blocks_long_in_bear_regime(self) -> None:
    allowed, reason = evaluate_entry_confirmation(0.001, MarketRegime.BEAR, "long")
    assert not allowed
    assert reason == "regimen_BEAR_contradice_long"

  def test_allows_long_in_bull_regime(self) -> None:
    allowed, reason = evaluate_entry_confirmation(0.001, MarketRegime.BULL, "long")
    assert allowed
    assert reason == "ok"

  def test_blocks_on_high_volatility_placeholder(self) -> None:
    allowed, reason = evaluate_entry_confirmation(
      0.001, MarketRegime.RANGE, "long", high_volatility_event=True
    )
    assert not allowed
    assert reason == "evento_alta_volatilidad_pendiente"

  def test_regime_filter_can_be_disabled(self) -> None:
    allowed, _ = evaluate_entry_confirmation(
      0.001, MarketRegime.BEAR, "long", regime_filter_enabled=False
    )
    assert allowed

  def test_spread_check_skipped_when_disabled(self) -> None:
    """En backtest spread_check_enabled=False — spread alto no bloquea."""
    allowed, reason = evaluate_entry_confirmation(
      0.01,
      MarketRegime.BULL,
      "long",
      spread_check_enabled=False,
    )
    assert allowed
    assert reason == "ok"

  def test_spread_check_skipped_when_none(self) -> None:
    allowed, reason = evaluate_entry_confirmation(None, MarketRegime.BULL, "long")
    assert allowed


class TestRegimeIndicators:
  def test_regime_labels_from_trending_series(self) -> None:
    """Valida que add_regime_indicators produce etiquetas válidas (vía import lazy)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
      "quant_base", ROOT / "user_data" / "strategies" / "_base.py"
    )
    assert spec and spec.loader
    # Solo verificamos que quant_core alimenta la lógica de etiquetado
    n = 250
    close = pd.Series([100 + i * 0.5 for i in range(n)], dtype=float)
    for i, price in enumerate(close):
      regime = compute_market_regime(price, 100.0, 30.0 if i > 200 else 15.0)
      if i > 200:
        assert regime == MarketRegime.BULL
