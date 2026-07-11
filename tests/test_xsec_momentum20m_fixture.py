"""Backtest fixture XSecMomentum20M — BNB cruza umbral liquidez 20M."""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def fixture20m_backtest_zip() -> Path:
  gen = ROOT / "tests" / "fixtures" / "generate_xsec_momentum_data.py"
  subprocess.run([__import__("sys").executable, str(gen)], cwd=str(ROOT), check=True)
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
    "XSecMomentum20M",
    "--strategy-path",
    "user_data/strategies",
    "--timerange",
    "20240101-20240430",
    "--cache",
    "none",
  ]
  proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
  if proc.returncode != 0:
    pytest.fail(f"fixture 20M backtest falló:\n{proc.stdout}\n{proc.stderr}")

  last = ROOT / "user_data" / "backtest_results" / ".last_result.json"
  data = json.loads(last.read_text(encoding="utf-8"))
  name = data.get("latest_backtest")
  path = ROOT / "user_data" / "backtest_results" / name
  return path


def _bnb_trades(zip_path: Path) -> list[dict]:
  with zipfile.ZipFile(zip_path) as zf:
    json_name = next(
      n for n in zf.namelist() if n.endswith(".json") and "_config" not in n and "meta" not in n
    )
    payload = json.loads(zf.read(json_name))
  block = payload.get("strategy", {}).get("XSecMomentum20M", {})
  trades = list(block.get("trades") or [])
  return [t for t in trades if "BNB" in str(t.get("pair", ""))]


def test_bnb_produces_trades_after_liquidity_threshold(fixture20m_backtest_zip: Path) -> None:
  trades = _bnb_trades(fixture20m_backtest_zip)
  assert len(trades) >= 1, "BNB debe operar tras cruzar umbral 20M"


def test_bnb_has_liquidity_or_rotation_exit(fixture20m_backtest_zip: Path) -> None:
  trades = _bnb_trades(fixture20m_backtest_zip)
  exit_tags = {t.get("exit_reason") or t.get("sell_reason") for t in trades}
  assert any(
    x and ("liquidity" in str(x).lower() or "xsec" in str(x).lower()) for x in exit_tags
  ), exit_tags
