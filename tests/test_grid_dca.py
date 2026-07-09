"""Tests unitarios GridDCA — presupuesto, BEAR freeze y causalidad ATR."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from quant_core import (  # noqa: E402
  MarketRegime,
  cap_dca_stake_to_budget,
  compute_dca_drop_threshold_pct,
  compute_dca_layer_stakes,
  evaluate_dca_adjustment,
  price_drop_pct_from_reference,
  projected_exposure_within_budget,
  regime_allows_grid_dca,
)


class TestRegimeAllowsGridDca:
  def test_bear_freezes_dca(self) -> None:
    assert not regime_allows_grid_dca(MarketRegime.BEAR)

  def test_bull_and_range_allow_dca(self) -> None:
    assert regime_allows_grid_dca(MarketRegime.BULL)
    assert regime_allows_grid_dca(MarketRegime.RANGE)


class TestDcaBudget:
  def test_layer_stakes_sum_to_max_budget(self) -> None:
    budget = 1500.0
    layers = compute_dca_layer_stakes(budget)
    assert sum(layers) == pytest.approx(budget)

  def test_cap_respects_headroom_with_partial_fill(self) -> None:
    capped = cap_dca_stake_to_budget(current_stake=1200.0, requested_stake=400.0, max_position_budget=1500.0)
    assert capped == pytest.approx(300.0)
    assert projected_exposure_within_budget(1200.0, capped, 1500.0)

  def test_bear_regime_blocks_adjustment(self) -> None:
    stake, reason = evaluate_dca_adjustment(
      successful_entries=1,
      max_additional_entries=3,
      current_stake=500.0,
      next_layer_stake=250.0,
      max_position_budget=1500.0,
      reference_entry_rate=100.0,
      current_rate=95.0,
      atr=2.0,
      regime=MarketRegime.BEAR,
    )
    assert stake is None
    assert reason == "regimen_BEAR_congela_dca"

  def test_trend_tag_ignores_range_exit_analog_on_dca(self) -> None:
    """Caída suficiente en BULL añade capa; BEAR no."""
    stake_bull, reason_bull = evaluate_dca_adjustment(
      successful_entries=1,
      max_additional_entries=3,
      current_stake=500.0,
      next_layer_stake=250.0,
      max_position_budget=1500.0,
      reference_entry_rate=100.0,
      current_rate=97.0,
      atr=2.0,
      regime=MarketRegime.BULL,
      min_drop_pct=0.02,
    )
    assert reason_bull == "ok"
    assert stake_bull == pytest.approx(250.0)

    stake_bear, _ = evaluate_dca_adjustment(
      successful_entries=1,
      max_additional_entries=3,
      current_stake=500.0,
      next_layer_stake=250.0,
      max_position_budget=1500.0,
      reference_entry_rate=100.0,
      current_rate=97.0,
      atr=2.0,
      regime=MarketRegime.BEAR,
      min_drop_pct=0.02,
    )
    assert stake_bear is None


class TestDcaCausalAtr:
  def test_drop_threshold_ignores_absurd_tail_atr(self) -> None:
    """Réplica del test ATR=999 en cola — umbral en t intermedio no usa cola."""
    dates = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
    df = pd.DataFrame({"date": dates, "atr": [2.0] * 9 + [999.0]})
    from quant_core import column_value_at_time

    mid = dates[5].to_pydatetime()
    atr_mid = column_value_at_time(df, "atr", mid, "1h")
    atr_tail = column_value_at_time(df, "atr", dates[-1].to_pydatetime(), "1h")

    th_mid = compute_dca_drop_threshold_pct(float(atr_mid), 100.0, min_drop_pct=0.02)
    th_if_tail = compute_dca_drop_threshold_pct(float(atr_tail), 100.0, min_drop_pct=0.02)

    assert atr_mid == 2.0
    assert th_mid < th_if_tail
    assert th_mid == pytest.approx(0.03, rel=0.01)

  def test_insufficient_drop_blocks_layer(self) -> None:
    drop = price_drop_pct_from_reference(100.0, 99.5)
    assert drop == pytest.approx(0.005)
    stake, reason = evaluate_dca_adjustment(
      successful_entries=1,
      max_additional_entries=3,
      current_stake=500.0,
      next_layer_stake=250.0,
      max_position_budget=1500.0,
      reference_entry_rate=100.0,
      current_rate=99.5,
      atr=2.0,
      regime=MarketRegime.BULL,
      min_drop_pct=0.02,
    )
    assert stake is None
    assert reason.startswith("caida_insuficiente")
