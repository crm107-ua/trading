"""Tests de resume granular walk-forward."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pipeline.strategy_warmup import earliest_train_start
from pipeline.walk_forward import generate_walk_forward_windows
from pipeline.wf_resume import (
  WfWindowRecord,
  adopt_or_recover_wf_window,
  evaluate_wf_adoption,
  save_wf_segment,
  wf_train_meta_path,
  wf_train_params_path,
)


def _windows_meanrevbb() -> list:
  data_start = date(2021, 1, 1)
  data_end = date(2026, 7, 9)
  wf_min = earliest_train_start(data_start, "MeanRevBB")
  return generate_walk_forward_windows(
    data_start,
    data_end,
    earliest_train_start=wf_min,
  )


def test_adopt_segment_with_matching_timerange(tmp_path: Path) -> None:
  windows = _windows_meanrevbb()
  w0 = windows[0]
  params_dir = tmp_path / "params"
  params_dir.mkdir()
  record = WfWindowRecord(
    window=0,
    train=w0.train_timerange,
    test=w0.test_timerange,
    params_file=str(params_dir / "wf0_train.json"),
    is_metrics={"profit_total_abs": -100},
    oos_metrics={"profit_total": -0.1, "profit_total_abs": -50, "trades": 10, "sharpe": -1},
    completed_at="2026-07-12T00:00:00+00:00",
  )
  save_wf_segment(params_dir, record)
  decision = evaluate_wf_adoption(w0, params_dir)
  assert decision.adopted is True
  assert "timerange OK" in decision.reason


def test_reject_segment_timerange_mismatch(tmp_path: Path) -> None:
  windows = _windows_meanrevbb()
  w0 = windows[0]
  params_dir = tmp_path / "params"
  params_dir.mkdir()
  record = WfWindowRecord(
    window=0,
    train="20210101-20220131",
    test="20220201-20220430",
    params_file=str(params_dir / "wf0_train.json"),
    is_metrics={},
    oos_metrics={"profit_total": 0, "profit_total_abs": 0, "trades": 0, "sharpe": 0},
    completed_at="2026-07-12T00:00:00+00:00",
  )
  save_wf_segment(params_dir, record)
  decision = evaluate_wf_adoption(w0, params_dir)
  assert decision.adopted is False
  assert "no coincide" in decision.reason


def test_reject_prefix_pc1_train_meta(tmp_path: Path) -> None:
  windows = _windows_meanrevbb()
  w0 = windows[0]
  params_dir = tmp_path / "params"
  params_dir.mkdir()
  train = wf_train_params_path(params_dir, 0)
  train.write_text("{}", encoding="utf-8")
  meta = {
    "hyperopt_timerange": "20210101-20220131",
    "label": "wf0_train",
  }
  wf_train_meta_path(params_dir, 0).write_text(json.dumps(meta), encoding="utf-8")
  decision = evaluate_wf_adoption(w0, params_dir)
  assert decision.adopted is False
  assert "rechazado" in decision.reason


def test_recover_from_train_params_without_segment(tmp_path: Path) -> None:
  windows = _windows_meanrevbb()
  w0 = windows[0]
  params_dir = tmp_path / "params"
  params_dir.mkdir()
  train = wf_train_params_path(params_dir, 0)
  train.write_text("{}", encoding="utf-8")

  def fake_backtest(
    timerange: str,
    params_file: Path,
    *,
    enable_protections: bool,
    allow_defaults: bool,
  ) -> tuple[dict, str, Path]:
    if timerange == w0.train_timerange:
      return {"profit_total_abs": -200}, "", tmp_path / "is.zip"
    return {
      "profit_total": -0.05,
      "profit_total_abs": -80,
      "trades": 12,
      "sharpe": -0.5,
    }, "", tmp_path / "oos.zip"

  record, decision = adopt_or_recover_wf_window(
    w0,
    params_dir,
    backtest=fake_backtest,
    enable_protections=True,
  )
  assert record is not None
  assert decision.adopted is True
  assert record.recovered is True
  assert (params_dir / "wf0.json").is_file()
