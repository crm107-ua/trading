"""Tests de screen_strategy — parseo de zip y veredicto (sin Docker)."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "tools"))

from screen_strategy import (  # noqa: E402
  VariantMetrics,
  evaluate_screen,
  parse_backtest_zip,
)


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
