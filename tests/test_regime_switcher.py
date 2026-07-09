"""Tests de dispatch enter_tag → señal de salida (RegimeSwitcher)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from quant_core import (  # noqa: E402
  MEAN_REV_ENTER_TAG,
  MEAN_REV_SIGNAL_EXIT_TAG,
  TREND_ENTER_TAG,
  TREND_SIGNAL_EXIT_TAG,
  resolve_regime_switcher_signal_exit,
)


def test_trend_ignores_range_exit_condition() -> None:
  assert resolve_regime_switcher_signal_exit(TREND_ENTER_TAG, False, True) is None


def test_mean_rev_ignores_trend_exit_condition() -> None:
  assert resolve_regime_switcher_signal_exit(MEAN_REV_ENTER_TAG, True, False) is None


def test_trend_exits_only_on_trend_condition() -> None:
  assert resolve_regime_switcher_signal_exit(TREND_ENTER_TAG, True, False) == TREND_SIGNAL_EXIT_TAG
  assert resolve_regime_switcher_signal_exit(TREND_ENTER_TAG, False, False) is None


def test_mean_rev_exits_only_on_range_condition() -> None:
  assert (
    resolve_regime_switcher_signal_exit(MEAN_REV_ENTER_TAG, False, True)
    == MEAN_REV_SIGNAL_EXIT_TAG
  )
  assert resolve_regime_switcher_signal_exit(MEAN_REV_ENTER_TAG, False, False) is None


def test_unknown_tag_never_signals() -> None:
  assert resolve_regime_switcher_signal_exit("other", True, True) is None
  assert resolve_regime_switcher_signal_exit(None, True, True) is None
