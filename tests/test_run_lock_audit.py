"""Tests de audit-log y heartbeat del lock de validación."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def lock_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
  lock_path = tmp_path / ".run_lock.json"
  audit_path = tmp_path / ".run_lock_audit.log"
  monkeypatch.setattr("pipeline.run_lock.LOCK_PATH", lock_path)
  monkeypatch.setattr("pipeline.run_lock.AUDIT_LOG_PATH", audit_path)
  monkeypatch.setenv("VALIDATION_LOCK_HEARTBEAT_MAX_HOURS", "0.001")
  return lock_path, audit_path


def _read_audit(audit_path: Path) -> list[dict]:
  if not audit_path.is_file():
    return []
  return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_acquire_release_writes_audit_log(lock_paths) -> None:
  lock_path, audit_path = lock_paths
  from pipeline.run_lock import acquire_lock, read_lock, release_lock

  acquire_lock(strategy="AuditTest", run_id="run1", profile="smoke")
  assert lock_path.is_file()
  release_lock()
  assert read_lock() is None

  ops = [e["op"] for e in _read_audit(audit_path)]
  assert ops == ["acquire", "release"]


def test_touch_lock_heartbeat_updates_timestamp(lock_paths) -> None:
  lock_path, audit_path = lock_paths
  from pipeline.run_lock import acquire_lock, touch_lock_heartbeat

  lock = acquire_lock(strategy="Hb", run_id="hb1", profile="full")
  first_hb = lock.heartbeat_at
  time.sleep(0.02)
  updated = touch_lock_heartbeat()
  assert updated is not None
  assert updated.heartbeat_at > first_hb
  data = json.loads(lock_path.read_text(encoding="utf-8"))
  assert data["started_at"] == lock.started_at
  assert data["heartbeat_at"] == updated.heartbeat_at
  ops = [e["op"] for e in _read_audit(audit_path)]
  assert ops.count("heartbeat") == 1


def test_stale_lock_cleared_by_old_heartbeat(lock_paths) -> None:
  lock_path, audit_path = lock_paths
  from pipeline.run_lock import LOCK_VERSION, read_lock

  old_hb = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
  lock_path.parent.mkdir(parents=True, exist_ok=True)
  lock_path.write_text(
    json.dumps(
      {
        "pid": 999999999,
        "strategy": "Zombie",
        "run_id": "z1",
        "profile": "full",
        "started_at": old_hb,
        "heartbeat_at": "2020-01-01T00:00:00+00:00",
        "hostname": "test",
        "lock_version": LOCK_VERSION,
      }
    ),
    encoding="utf-8",
  )
  assert read_lock() is None
  assert not lock_path.is_file()
  assert any(e["op"] == "stale_clear" for e in _read_audit(audit_path))


def test_resume_run_leaves_lock_during_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  """--resume-run-id debe adquirir lock al arrancar (antes de liberarlo al terminar)."""
  from datetime import date

  from pipeline import run_validation as rv
  from pipeline.run_lock import read_lock
  from pipeline.timerange_split import IsOosSplit

  lock_path = tmp_path / "validation_reports" / ".run_lock.json"
  audit_path = tmp_path / "validation_reports" / ".run_lock_audit.log"
  reports_dir = tmp_path / "validation_reports"
  monkeypatch.setattr("pipeline.run_lock.LOCK_PATH", lock_path)
  monkeypatch.setattr("pipeline.run_lock.AUDIT_LOG_PATH", audit_path)

  strategy = "ResumeLockTest"
  run_id = "20260101_120000"
  run_path = reports_dir / strategy / run_id
  run_path.mkdir(parents=True)
  (run_path / "checkpoint.json").write_text(
    json.dumps(
      {
        "run_id": run_id,
        "strategy": strategy,
        "baseline_oos": {"sharpe": 0.5, "trades": 50, "profit_total": 0.1},
        "completed_seeds": [],
        "seed_results": [],
        "seed_params_raw": [],
      }
    ),
    encoding="utf-8",
  )

  data_dir = tmp_path / "data"
  data_dir.mkdir()
  (data_dir / "BTC_USDT-1h.feather").write_bytes(b"")

  split = IsOosSplit(
    full_timerange="20220101-20240630",
    full_start=date(2022, 1, 1),
    full_end=date(2024, 6, 30),
    is_start=date(2022, 1, 1),
    is_end=date(2023, 12, 31),
    oos_start=date(2024, 1, 1),
    oos_end=date(2024, 6, 30),
    is_timerange="20220101-20231231",
    oos_timerange="20240101-20240630",
  )

  monkeypatch.setattr(rv, "REPORTS_DIR", reports_dir)
  monkeypatch.setattr(rv, "DATA_DIR", data_dir)
  monkeypatch.setattr(rv, "resolve_data_end", lambda _d: date(2024, 6, 30))
  monkeypatch.setattr(rv, "compute_is_oos_split", lambda _tr, data_end: split)
  monkeypatch.setattr(rv, "regime_distribution_for_timerange", lambda _tr: {})
  monkeypatch.setattr(rv, "config_metadata", lambda: {"config_merged_sha256": "0" * 64, "config_files": []})
  monkeypatch.setattr(rv, "docker_runtime_info", lambda: {})
  monkeypatch.setattr(rv, "hyperopt_job_workers", lambda: 1)
  monkeypatch.setattr(rv, "hyperopt_spaces_for", lambda _s: ["buy"])
  monkeypatch.setattr(rv, "clear_strategy_params", lambda _s: None)

  real_touch = rv.touch_lock_heartbeat

  def slow_touch() -> None:
    time.sleep(0.25)
    return real_touch()

  monkeypatch.setattr(rv, "touch_lock_heartbeat", slow_touch)

  def run_validate() -> None:
    rv._run_validation(
      strategy=strategy,
      timerange="20220101-",
      profile=rv.Profile.smoke,
      epochs=None,
      seeds=None,
      enable_protections=False,
      skip_walk_forward=True,
      skip_hyperopt=True,
      resume_run_id=run_id,
      adopt_partial_hyperopt=False,
      wf_epochs=None,
    )

  thread = threading.Thread(target=run_validate)
  thread.start()
  deadline = time.time() + 5.0
  lock = None
  while time.time() < deadline:
    lock = read_lock()
    if lock is not None and lock.strategy == strategy:
      break
    time.sleep(0.02)
  assert lock is not None, "resume no adquirió lock tras arranque"
  assert lock.run_id == run_id
  thread.join(timeout=10)
  assert read_lock() is None


def test_record_step_git_tracks_hashes() -> None:
  from pipeline.git_provenance import current_git_hash, record_step_git

  report: dict = {"git_hash": current_git_hash()}
  record_step_git(report, "seeds")
  record_step_git(report, "walk_forward")
  prov = report["pipeline_provenance"]
  assert prov["repo_git_hash_at_start"] == report["git_hash"]
  assert "seeds" in prov["steps"]
  assert "walk_forward" in prov["steps"]
  assert prov["steps"]["seeds"]["git_hash"]
