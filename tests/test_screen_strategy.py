"""Tests de screen_strategy — parseo, params JSON, guard y veredicto (sin Docker)."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "tools"))
sys.path.insert(0, str(ROOT))

from screen_strategy import (  # noqa: E402
  ScreenAbortError,
  VariantMetrics,
  _pipeline_mutable_state_guard,
  assert_screen_allowed,
  build_variant_params_export,
  detect_identical_variants,
  evaluate_screen,
  parse_backtest_zip,
  verify_defaults_loaded,
  write_variant_params_file,
)
from pipeline.params_manager import strategy_params_path  # noqa: E402


def _write_smoke_zip(path: Path) -> None:
  payload = {
    "strategy": {
      "TrendRider": {
        "total_trades": 40,
        "profit_total_abs": 120.0,
        "sharpe": 0.5,
        "max_drawdown_account": 0.08,
        "trades": [
          {"fee": 10.0},
          {"fee": 12.0},
        ],
      }
    }
  }
  path.parent.mkdir(parents=True, exist_ok=True)
  with zipfile.ZipFile(path, "w") as zf:
    zf.writestr("backtest-result.json", json.dumps(payload))


def test_parse_backtest_zip_gross_and_fees(tmp_path: Path) -> None:
  z = tmp_path / "backtest-result-smoke.zip"
  _write_smoke_zip(z)
  m = parse_backtest_zip(z, "TrendRider")
  assert m.trades == 40
  assert m.profit_net_abs == 120.0
  assert m.total_fees_abs == 22.0
  assert m.profit_gross_abs == 142.0


def test_evaluate_screen_pass_and_discard() -> None:
  ok = VariantMetrics(
    name="a",
    strategy_parameters={},
    zip_path="x",
    trades=40,
    profit_net_abs=100,
    profit_gross_abs=200,
    total_fees_abs=50,
    sharpe=1.0,
    max_drawdown_account=0.1,
    friction_ratio=0.25,
  )
  assert evaluate_screen([ok]).verdict == "PASA"

  bad = VariantMetrics(
    name="b",
    strategy_parameters={},
    zip_path="x",
    trades=10,
    profit_net_abs=-5,
    profit_gross_abs=-5,
    total_fees_abs=0,
    sharpe=-1,
    max_drawdown_account=0.2,
    friction_ratio=None,
  )
  assert evaluate_screen([bad]).verdict == "DESCARTADA"

  grey = VariantMetrics(
    name="c",
    strategy_parameters={},
    zip_path="x",
    trades=10,
    profit_net_abs=50,
    profit_gross_abs=100,
    total_fees_abs=60,
    sharpe=0.2,
    max_drawdown_account=0.1,
    friction_ratio=0.6,
  )
  assert evaluate_screen([grey]).verdict == "ZONA_GRIS"


def test_build_variant_params_export_full_buy_block() -> None:
  payload = build_variant_params_export(
    "TrendRider",
    {"buy_adx": 30, "buy_rsi_max": 68},
  )
  assert payload is not None
  buy = payload["params"]["buy"]
  assert buy["buy_adx"] == 30
  assert buy["buy_rsi_max"] == 68
  assert buy["buy_ema_fast"] == 12
  assert payload["ft_stratparam_v"] == 1


def test_build_variant_params_rejects_atr_stop() -> None:
  with pytest.raises(ScreenAbortError, match="no cargables"):
    build_variant_params_export("TrendRider", {"atr_stop_multiplier": 3.0})


def test_write_variant_params_file(tmp_path: Path) -> None:
  dest = tmp_path / "TrendRider_variant.json"
  path = write_variant_params_file("BreakoutVol", {"buy_breakout_period": 35}, dest)
  assert path == dest
  data = json.loads(dest.read_text(encoding="utf-8"))
  assert data["params"]["buy"]["buy_breakout_period"] == 35
  assert data["params"]["buy"]["buy_volume_factor"] == 15


def test_snapshot_restore_strategy_json_no_prior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  strat_json = tmp_path / "strategies" / "SmokeStrat.json"
  strat_json.parent.mkdir(parents=True)
  monkeypatch.setattr(
    "screen_strategy.strategy_params_path",
    lambda _s: strat_json,
  )
  monkeypatch.setattr(
    "screen_strategy.LAST_RESULT",
    tmp_path / "backtest_results" / ".last_result.json",
  )
  monkeypatch.setattr(
    "screen_strategy.HYPEROPT_LAST_RESULT",
    tmp_path / "hyperopt_results" / ".last_result.json",
  )

  assert not strat_json.exists()
  with _pipeline_mutable_state_guard("SmokeStrat"):
    strat_json.write_text('{"strategy_name":"SmokeStrat"}', encoding="utf-8")
    assert strat_json.is_file()
  assert not strat_json.exists()


def test_snapshot_restore_strategy_json_with_prior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  strat_json = tmp_path / "strategies" / "SmokeStrat.json"
  strat_json.parent.mkdir(parents=True)
  original = '{"strategy_name":"SmokeStrat","params":{"buy":{"buy_adx":25}}}'
  strat_json.write_text(original, encoding="utf-8")

  monkeypatch.setattr(
    "screen_strategy.strategy_params_path",
    lambda _s: strat_json,
  )
  monkeypatch.setattr(
    "screen_strategy.LAST_RESULT",
    tmp_path / "backtest_results" / ".last_result.json",
  )
  monkeypatch.setattr(
    "screen_strategy.HYPEROPT_LAST_RESULT",
    tmp_path / "hyperopt_results" / ".last_result.json",
  )

  with _pipeline_mutable_state_guard("SmokeStrat"):
    strat_json.write_text('{"strategy_name":"SmokeStrat","params":{"buy":{"buy_adx":30}}}', encoding="utf-8")
  assert strat_json.read_text(encoding="utf-8") == original


def test_detect_identical_variants() -> None:
  a = VariantMetrics("a", {}, "z", 10, 1.0, 2.0, 1.0, 0.1, 0.05, 0.5)
  b = VariantMetrics("b", {}, "z", 10, 1.0, 2.0, 1.0, 0.1, 0.05, 0.5)
  c = VariantMetrics("c", {}, "z", 11, 1.0, 2.0, 1.0, 0.1, 0.05, 0.5)
  twins, details = detect_identical_variants([a, b, c])
  assert twins is True
  assert any("a" in d and "b" in d for d in details)


def test_meanrevbb_guard_blocks_locked_strategy() -> None:
  class FakeLock:
    strategy = "MeanRevBB"
    run_id = "20260709_162954"
    pid = 38004

  with patch("pipeline.run_lock.read_lock", return_value=FakeLock()):
    with pytest.raises(ScreenAbortError, match="vetado"):
      assert_screen_allowed("MeanRevBB")


def test_meanrevbb_guard_allows_other_strategy() -> None:
  class FakeLock:
    strategy = "MeanRevBB"
    run_id = "20260709_162954"
    pid = 38004

  with patch("pipeline.run_lock.read_lock", return_value=FakeLock()):
    assert_screen_allowed("TrendRider")


def test_verify_defaults_loaded() -> None:
  log = "Found no parameter file.\nStrategy Parameter(default): buy_adx = 25"
  ok, issues = verify_defaults_loaded(log)
  assert ok is True
  assert issues == []

  bad_log = "Loading parameters from file /freqtrade/user_data/strategies/TrendRider.json"
  ok, issues = verify_defaults_loaded(bad_log)
  assert ok is False
  assert issues


def test_strategy_params_path_meanrevbb_not_written_by_guard_test() -> None:
  """Sanity: path de MeanRevBB.json es el vetado por el lock guard."""
  path = strategy_params_path("MeanRevBB")
  assert path.name == "MeanRevBB.json"
