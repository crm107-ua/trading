"""Backtest de fixture XSecMomentum — entradas, rotación y plano BEAR."""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def fixture_backtest_zip() -> Path:
  cmd = [
    "docker",
    "compose",
    "run",
    "--rm",
    "--no-deps",
    "freqtrade",
    "backtesting",
    "--config",
    "user_data/config/base.json",
    "--config",
    "user_data/config/backtest.json",
    "--config",
    "user_data/config/backtest_xsec_momentum_fixtures.json",
    "--datadir",
    "tests/fixtures/data_xsec_momentum/binance",
    "--strategy",
    "XSecMomentum",
    "--strategy-path",
    "user_data/strategies",
    "--timerange",
    "20240101-20240430",
    "--cache",
    "none",
  ]
  proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
  if proc.returncode != 0:
    pytest.fail(f"fixture backtest falló:\n{proc.stdout}\n{proc.stderr}")

  last = ROOT / "user_data" / "backtest_results" / ".last_result.json"
  data = json.loads(last.read_text(encoding="utf-8"))
  name = data.get("latest_backtest")
  assert name, "sin latest_backtest tras fixture backtest"
  path = ROOT / "user_data" / "backtest_results" / name
  assert path.is_file()
  return path


def _strategy_block(zip_path: Path) -> dict:
  with zipfile.ZipFile(zip_path) as zf:
    json_name = next(
      n for n in zf.namelist() if n.endswith(".json") and "_config" not in n and "meta" not in n
    )
    payload = json.loads(zf.read(json_name))
  block = payload.get("strategy", {}).get("XSecMomentum")
  assert block, "bloque XSecMomentum ausente"
  return block


def test_fixture_produces_trades(fixture_backtest_zip: Path) -> None:
  block = _strategy_block(fixture_backtest_zip)
  trades = list(block.get("trades") or [])
  assert len(trades) >= 3, "fixture debe generar rotaciones reales, no 0 trades"


def test_fixture_has_rotation_and_bear_exits(fixture_backtest_zip: Path) -> None:
  block = _strategy_block(fixture_backtest_zip)
  trades = list(block.get("trades") or [])
  exit_tags = {t.get("exit_reason") or t.get("sell_reason") for t in trades}
  assert any("xsec" in str(x).lower() for x in exit_tags if x), exit_tags
