"""Tests unitarios del pipeline Fase 4 (sin hyperopt Docker)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pipeline.params_manager import (
  flatten_params_export,
  param_divergence,
  parse_loaded_params_from_log,
  verify_params_loaded,
)
from pipeline.timerange_split import compute_is_oos_split, format_timerange
from pipeline.verdict import Verdict
from pipeline.verdict_engine import SeedRunResult, VerdictInput, compute_verdict
from pipeline.walk_forward import generate_walk_forward_windows, stitch_oos_equity, walk_forward_efficiency


def test_is_oos_split_absolute_dates() -> None:
  split = compute_is_oos_split("20210101-20231231")
  assert split.is_start == date(2021, 1, 1)
  assert split.is_end < split.oos_start
  assert split.oos_end == date(2023, 12, 31)
  assert split.is_timerange == format_timerange(split.is_start, split.is_end)
  assert split.oos_timerange == format_timerange(split.oos_start, split.oos_end)
  # Reproducible — mismo resultado
  split2 = compute_is_oos_split("20210101-20231231")
  assert split2.is_end == split.is_end


def test_walk_forward_generates_multiple_windows() -> None:
  windows = generate_walk_forward_windows(date(2021, 1, 1), date(2026, 7, 1))
  assert len(windows) >= 4
  assert windows[0].train_start == date(2021, 1, 1)
  assert windows[0].test_start > windows[0].train_end


def test_stitch_oos_carries_capital() -> None:
  from pipeline.walk_forward import OosSegmentResult

  segments = [
    OosSegmentResult(0, 0.10, 1000, 10, 1.0, 0, 0),
    OosSegmentResult(1, -0.05, -500, 8, -0.5, 0, 0),
    OosSegmentResult(2, 0.02, 200, 5, 0.3, 0, 0),
  ]
  stitched = stitch_oos_equity(segments, initial_capital=10_000.0)
  assert stitched["final_capital"] == pytest.approx(10_000 * 1.10 * 0.95 * 1.02)


def test_param_divergence_identical() -> None:
  params = {"params": {"buy": {"x": 1}, "sell": {"y": 2}}}
  assert param_divergence(params, params) == 0.0


def test_verify_params_loaded_from_log() -> None:
  expected = {
    "params": {
      "buy": {"buy_rsi_max": 45},
      "sell": {},
    }
  }
  path = Path("tmp_params.json")
  path.write_text(json.dumps(expected), encoding="utf-8")
  log = "Strategy Parameter: buy_rsi_max = 45\n"
  ok, issues = verify_params_loaded(path, log, allow_defaults=False)
  path.unlink()
  assert ok, issues


def test_parse_loaded_params() -> None:
  log = "Strategy Parameter(default): buy_rsi_max = 48\nStrategy Parameter: dca_min_drop_pct = 0.015\n"
  loaded = parse_loaded_params_from_log(log)
  assert loaded["buy_rsi_max"] == "48"
  assert loaded["dca_min_drop_pct"] == "0.015"


def test_mean_rev_control_pure_metrics_can_be_robusta() -> None:
  """Sin regla especial: veredicto = función pura de métricas."""
  seed = SeedRunResult(
    seed=42,
    is_metrics={"sharpe": 2.0, "trades": 200, "profit_total": 0.5},
    oos_metrics={"sharpe": 2.0, "trades": 80, "profit_total": 0.3},
    params_file="x.json",
  )
  out = compute_verdict(
    VerdictInput(
      strategy="MeanRevBB",
      baseline_oos_metrics=None,
      seed_results=[seed],
      walk_forward_efficiency=0.8,
      max_param_divergence=0.0,
    )
  )
  assert out.verdict == Verdict.ROBUSTA


def test_oos_negative_is_sobreajustada() -> None:
  seed = SeedRunResult(
    seed=42,
    is_metrics={"sharpe": 1.5, "trades": 150, "profit_total": 0.4},
    oos_metrics={"sharpe": -0.5, "trades": 50, "profit_total": -0.1},
    params_file="x.json",
  )
  out = compute_verdict(
    VerdictInput(
      strategy="TrendRider",
      baseline_oos_metrics=None,
      seed_results=[seed],
      walk_forward_efficiency=None,
      max_param_divergence=0.0,
    )
  )
  assert out.verdict == Verdict.SOBREAJUSTADA


def test_grid_dca_hyperopt_spaces_buy_only() -> None:
  from pipeline.strategy_spaces import hyperopt_spaces_for

  assert hyperopt_spaces_for("GridDCA") == ["buy"]
  assert hyperopt_spaces_for("MeanRevBB") == ["buy", "sell"]


def test_walk_forward_efficiency() -> None:
  assert walk_forward_efficiency([1000, 500], [400, 200]) == pytest.approx(0.4)


def test_hyperopt_job_workers_default() -> None:
  from pipeline.freqtrade_cli import hyperopt_job_workers

  assert hyperopt_job_workers() >= 1


def test_pipeline_host_no_freqtrade_or_talib_imports() -> None:
  """El orquestador local no debe importar talib/freqtrade/estrategias en host."""
  import ast

  root = Path(__file__).resolve().parents[1] / "pipeline"
  forbidden = {"talib", "freqtrade", "_base", "QuantBaseStrategy"}
  for path in root.glob("*.py"):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
      if isinstance(node, ast.Import):
        for alias in node.names:
          top = alias.name.split(".")[0]
          assert top not in forbidden, f"{path.name} importa {alias.name} en host"
      elif isinstance(node, ast.ImportFrom):
        if node.module:
          top = node.module.split(".")[0]
          assert top not in forbidden, f"{path.name} importa from {node.module} en host"


def test_regime_stats_host_code_uses_docker_subprocess() -> None:
  import ast

  path = Path(__file__).resolve().parents[1] / "pipeline" / "regime_stats.py"
  tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
  host_imports = []
  for node in ast.walk(tree):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
      # Solo imports a nivel de módulo (no dentro del script embebido)
      if getattr(node, "col_offset", 0) == 0 and node.lineno < 18:
        host_imports.append(node)
  host_names = []
  for node in host_imports:
    if isinstance(node, ast.Import):
      host_names.extend(a.name.split(".")[0] for a in node.names)
    elif node.module:
      host_names.append(node.module.split(".")[0])
  assert "pandas" not in host_names
  assert "talib" not in host_names
  text = path.read_text(encoding="utf-8")
  assert "docker" in text and "subprocess" in text


def test_run_lock_acquire_and_release() -> None:
  from pipeline.run_lock import LOCK_PATH, acquire_lock, read_lock, release_lock

  LOCK_PATH.unlink(missing_ok=True)
  acquire_lock(strategy="Test", run_id="test_run", profile="smoke")
  lock = read_lock()
  assert lock is not None
  assert lock.strategy == "Test"
  assert lock.pid > 0
  assert lock.started_at
  assert lock.hostname
  release_lock()
  assert read_lock() is None


def test_run_lock_clears_orphan_pid() -> None:
  import json

  from pipeline.run_lock import LOCK_PATH, read_lock

  LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
  LOCK_PATH.write_text(
    json.dumps(
      {
        "pid": 999999999,
        "strategy": "Ghost",
        "run_id": "orphan",
        "profile": "full",
        "started_at": "2020-01-01T00:00:00+00:00",
        "hostname": "test",
        "lock_version": 1,
      }
    ),
    encoding="utf-8",
  )
  assert read_lock() is None
  assert not LOCK_PATH.is_file()


def test_run_lock_preserves_alive_subprocess() -> None:
  """Regresión: limpieza de huérfanos no debe matar lock de PID vivo (Windows)."""
  import subprocess
  import sys
  import textwrap
  import time
  from pathlib import Path

  from pipeline.run_lock import LOCK_PATH, clear_stale_lock, read_lock

  root = Path(__file__).resolve().parents[1]
  LOCK_PATH.unlink(missing_ok=True)
  holder = textwrap.dedent(
    """
    import time
    from pipeline.run_lock import acquire_lock
    acquire_lock(strategy="Holder", run_id="hold", profile="test")
    time.sleep(60)
    """
  )
  proc = subprocess.Popen([sys.executable, "-c", holder], cwd=str(root))
  try:
    deadline = time.time() + 10.0
    lock = None
    while time.time() < deadline:
      lock = read_lock()
      if lock is not None and lock.pid == proc.pid:
        break
      time.sleep(0.2)
    assert lock is not None, "subproceso no adquirió lock a tiempo"
    assert lock.pid == proc.pid

    cleared = clear_stale_lock()
    assert cleared is None
    assert read_lock() is not None
    assert LOCK_PATH.is_file()
  finally:
    proc.terminate()
    try:
      proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
      proc.kill()
      proc.wait(timeout=5)

  cleared = clear_stale_lock()
  assert cleared is not None
  assert read_lock() is None


def test_docker_image_digest_constant() -> None:
  from pipeline.docker_image import FREQTRADE_IMAGE_DIGEST, FREQTRADE_IMAGE_PINNED

  assert FREQTRADE_IMAGE_DIGEST.startswith("sha256:")
  assert FREQTRADE_IMAGE_DIGEST in FREQTRADE_IMAGE_PINNED


def test_high_param_divergence_yields_dudosa() -> None:
  """max_param_divergence se consume en el motor — no es decorativo."""
  seed = SeedRunResult(
    seed=42,
    is_metrics={"sharpe": 2.0, "trades": 200, "profit_total": 0.5},
    oos_metrics={"sharpe": 1.5, "trades": 80, "profit_total": 0.3},
    params_file="x.json",
  )
  out = compute_verdict(
    VerdictInput(
      strategy="MeanRevBB",
      baseline_oos_metrics=None,
      seed_results=[seed],
      walk_forward_efficiency=0.8,
      max_param_divergence=0.5,
    )
  )
  assert out.verdict == Verdict.DUDOSA
  assert any("inestabilidad" in r for r in out.reasons)


def test_merged_config_hash_stable() -> None:
  from pipeline.config_hash import config_metadata, merged_config_hash

  h1 = merged_config_hash()
  h2 = merged_config_hash()
  meta = config_metadata()
  assert h1 == h2
  assert len(meta["config_merged_sha256"]) == 64
  assert "user_data/config/base.json" in meta["config_files"]
