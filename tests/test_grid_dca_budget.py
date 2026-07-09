"""Property-based tests del invariante de presupuesto GridDCA."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from quant_core import (  # noqa: E402
  cap_dca_stake_to_budget,
  compute_dca_layer_stakes,
  projected_exposure_within_budget,
)

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
import hypothesis.strategies as st  # noqa: E402


@given(
  budget=st.floats(min_value=100.0, max_value=50_000.0),
  fill_ratios=st.lists(
    st.floats(min_value=0.0, max_value=1.0),
    min_size=4,
    max_size=4,
  ),
)
@settings(max_examples=200, deadline=None)
def test_cumulative_partial_fills_never_exceed_budget(
  budget: float,
  fill_ratios: list[float],
) -> None:
  layers = compute_dca_layer_stakes(budget)
  assert len(layers) == 4
  exposure = 0.0
  for layer_stake, ratio in zip(layers, fill_ratios):
    requested = layer_stake * ratio
    additional = cap_dca_stake_to_budget(exposure, requested, budget)
    assert projected_exposure_within_budget(exposure, additional, budget)
    exposure += additional
  assert exposure <= budget + 1e-6
