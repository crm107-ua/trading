"""Tests infraestructura dry-run Fase 5."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_dryrun_config_isolated_from_pipeline() -> None:
  cfg = json.loads((ROOT / "user_data" / "config" / "dryrun_xsec.json").read_text(encoding="utf-8"))
  text = json.dumps(cfg)
  assert "validation_reports" not in text
  assert "hyperopt_results" not in text
  assert cfg["db_url"].endswith("dryrun_xsec.sqlite")
  assert cfg["api_server"]["listen_port"] == 8082


def test_dryrun_compose_separate_from_lab() -> None:
  dry = (ROOT / "docker-compose.dryrun.yml").read_text(encoding="utf-8")
  assert "xsec-dryrun" in dry
  assert "8082:8082" in dry
  assert "pipeline" not in dry
  main = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
  assert "xsec-dryrun" not in main


def test_m35_frozen_params() -> None:
  p = json.loads((ROOT / "user_data" / "strategies" / "XSecMomentum_m35_frozen.json").read_text())
  assert p["params"]["stoploss"]["stoploss"] == pytest.approx(-0.35)
  assert p["params"]["buy"]["momentum_window"] == 14
  assert p["params"]["buy"]["top_n"] == 3


def test_monitor_entry_weekday_alert() -> None:
  from risk.monitor import check_entry_weekdays

  alerts = check_entry_weekdays(
    [{"pair": "BTC/USDT", "open_date": "2026-07-11T00:00:00+00:00"}]
  )
  assert len(alerts) == 1
  assert alerts[0].code == "rebalance_timing_violation"


def test_monitor_drawdown_alert() -> None:
  from risk.monitor import evaluate_alerts

  alerts = evaluate_alerts(
    ping_ok=True,
    open_trades=[],
    profit_payload={"max_drawdown": 0.20},
  )
  assert any(a.code == "drawdown_high" for a in alerts)


def test_gap_report_synthetic(tmp_path: Path) -> None:
  import sys

  sys.path.insert(0, str(ROOT / "user_data" / "tools"))
  from dryrun_gap_report import compute_gap, TradeRow

  dry = [
    TradeRow("BTC/USDT", "2026-07-08T00:00:00+00:00", "2026-07-15T00:00:00+00:00", 100.0, 105.0, 50.0, False),
  ]
  bt = [
    TradeRow("BTC/USDT", "2026-07-08T00:00:00+00:00", "2026-07-15T00:00:00+00:00", 100.0, 105.0, 48.0, False),
  ]
  r = compute_gap(dry, bt, timerange="20260701-20260731")
  assert r.dryrun_trades == 1
  assert r.within_pnl_threshold is True


def test_gap_report_sqlite_fixture(tmp_path: Path) -> None:
  import sys

  sys.path.insert(0, str(ROOT / "user_data" / "tools"))
  from dryrun_gap_report import load_trades_from_sqlite, load_trades_from_zip, compute_gap

  db = tmp_path / "t.sqlite"
  conn = sqlite3.connect(db)
  conn.execute(
    """
    CREATE TABLE trades (
      pair TEXT, open_date TEXT, close_date TEXT, open_rate REAL,
      close_rate REAL, close_profit_abs REAL, is_open INTEGER
    )
    """
  )
  conn.execute(
    "INSERT INTO trades VALUES (?,?,?,?,?,?,?)",
    ("ETH/USDT", "2026-07-01T00:00:00+00:00", "2026-07-08T00:00:00+00:00", 3000, 3100, 100, 0),
  )
  conn.commit()
  conn.close()

  zpath = tmp_path / "bt.zip"
  payload = {
    "strategy": {
      "XSecMomentum": {
        "trades": [
          {
            "pair": "ETH/USDT",
            "open_date": "2026-07-01T00:00:00+00:00",
            "close_date": "2026-07-08T00:00:00+00:00",
            "open_rate": 3000,
            "close_rate": 3100,
            "profit_abs": 95,
            "is_open": False,
          }
        ]
      }
    }
  }
  with zipfile.ZipFile(zpath, "w") as zf:
    zf.writestr("backtest-result.json", json.dumps(payload))

  report = compute_gap(
    load_trades_from_sqlite(db),
    load_trades_from_zip(zpath),
    timerange="20260701-20260731",
  )
  assert report.dryrun_pnl == 100
  assert report.backtest_pnl == 95


def test_weekly_report_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  import sys

  sys.path.insert(0, str(ROOT / "scripts"))
  import weekly_report as wr

  monkeypatch.setattr(wr, "MONITOR_STATE", tmp_path / "mon.json")
  (tmp_path / "mon.json").write_text(
    json.dumps({"bot_ok": True, "open_trades": 0, "alerts": []}),
    encoding="utf-8",
  )
  out = tmp_path / "w.md"
  out.write_text(wr.build_report_markdown(), encoding="utf-8")
  assert "Dry-run" in out.read_text(encoding="utf-8")


def test_go_live_check_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
  import sys

  sys.path.insert(0, str(ROOT / "scripts"))
  import go_live_check as gl

  results = gl.run_checks("XSecMomentum", manual_withdraw=False)
  by_name = {r.name: r for r in results}
  assert by_name["verdict_robusta"].status == "FAIL"
  assert by_name["brecha_criterios"].status == "FAIL"
  monkeypatch.setattr(sys, "argv", ["go_live_check.py"])
  assert gl.main() == 1


def test_pipeline_resume_checkpoint_readable() -> None:
  """Resume: checkpoint JSON legible sin ejecutar run_validation."""
  ck_dir = ROOT / "user_data" / "validation_reports" / "MeanRevBB"
  if not ck_dir.is_dir():
    pytest.skip("sin checkpoints MeanRevBB")
  checkpoints = list(ck_dir.glob("*/checkpoint.json"))
  if not checkpoints:
    pytest.skip("sin checkpoint.json")
  data = json.loads(checkpoints[0].read_text(encoding="utf-8"))
  assert isinstance(data, dict)
