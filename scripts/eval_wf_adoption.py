#!/usr/bin/env python3
"""Evalúa adoptabilidad de ventanas WF en disco (sin Docker)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.strategy_warmup import earliest_train_start
from pipeline.timerange_split import compute_is_oos_split, resolve_data_end
from pipeline.walk_forward import generate_walk_forward_windows
from pipeline.wf_resume import evaluate_wf_adoption

RUN_ID = "20260709_162954"
STRATEGY = "MeanRevBB"


def main() -> None:
  data_end = resolve_data_end(ROOT / "user_data/data/binance")
  split = compute_is_oos_split(f"20210101-{data_end.strftime('%Y%m%d')}", data_end=data_end)
  wf_min = earliest_train_start(split.full_start, STRATEGY)
  windows = generate_walk_forward_windows(
    split.full_start, split.full_end, earliest_train_start=wf_min
  )
  params = ROOT / "user_data/validation_reports" / STRATEGY / RUN_ID / "params"
  for w in windows:
    d = evaluate_wf_adoption(w, params)
    flag = "ADOPT" if d.adopted else "SKIP "
    print(f"{flag} v{w.index}: {d.reason}")


if __name__ == "__main__":
  main()
