#!/usr/bin/env python3
"""Progreso total de validación full (semillas + walk-forward)."""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from pipeline.hyperopt_resume import count_fthypt_epochs, list_strategy_fthypt_files
from pipeline.strategy_warmup import earliest_train_start, warmup_days
from pipeline.timerange_split import compute_is_oos_split, resolve_data_end
from pipeline.walk_forward import generate_walk_forward_windows

REPORTS = ROOT / "user_data" / "validation_reports"
DATA_DIR = ROOT / "user_data" / "data" / "binance"
OUT_LOG = ROOT / "user_data" / "logs" / "pm2_meanrevbb.out.log"
SEEDS = (42, 123, 456)
PROFILE_EPOCHS = 300


def _newest_fthypt(strategy: str) -> Path | None:
  files = list_strategy_fthypt_files(strategy)
  if not files:
    return None
  return max(files, key=lambda p: p.stat().st_mtime)


def _parse_wf_from_log(log_path: Path) -> tuple[int | None, int, bool]:
  """(ventana_actual, ventanas_train_completadas, en_backtest)."""
  if not log_path.is_file():
    return None, 0, False
  text = log_path.read_text(encoding="utf-8", errors="replace")
  current: int | None = None
  completed: set[int] = set()
  in_test = False
  for line in text.splitlines():
    clean = re.sub(r"^\d{4}-\d{2}-\d{2}T[\d:.]+:\s*", "", line)
    m_train = re.search(r"ventana (\d+): train", clean)
    if m_train:
      current = int(m_train.group(1))
      in_test = False
    m_test = re.search(r"ventana (\d+): test", clean)
    if m_test:
      completed.add(int(m_test.group(1)))
      in_test = True
  return current, len(completed), in_test


def _wf_window_count(strategy: str) -> int:
  data_end = resolve_data_end(DATA_DIR)
  split = compute_is_oos_split(f"20210101-{data_end.strftime('%Y%m%d')}", data_end=data_end)
  wf_train_min = earliest_train_start(split.full_start, strategy)
  windows = generate_walk_forward_windows(
    split.full_start,
    split.full_end,
    earliest_train_start=wf_train_min,
  )
  return len(windows)


def compute_progress(
  *,
  strategy: str,
  run_id: str,
  epochs: int = PROFILE_EPOCHS,
  seeds: int = len(SEEDS),
) -> dict:
  run_path = REPORTS / strategy / run_id
  ck_path = run_path / "checkpoint.json"
  completed_seeds = 0
  if ck_path.is_file():
    ck = json.loads(ck_path.read_text(encoding="utf-8"))
    completed_seeds = len(ck.get("completed_seeds") or [])

  seed_units = seeds * epochs
  wf_windows = _wf_window_count(strategy)
  wf_units = wf_windows * epochs
  total_units = seed_units + wf_units

  seed_done_units = min(completed_seeds, seeds) * epochs

  current_wf, wf_train_done, in_test = _parse_wf_from_log(OUT_LOG)
  wf_done_units = wf_train_done * epochs

  active_epochs = 0
  fthypt = _newest_fthypt(strategy)
  fthypt_name = fthypt.name if fthypt else None
  if fthypt and not in_test and current_wf is not None:
    active_epochs = min(count_fthypt_epochs(fthypt), epochs)

  done_units = seed_done_units + wf_done_units + active_epochs
  pct = round(100.0 * done_units / total_units, 1) if total_units else 0.0

  if run_path.joinpath("report.json").is_file():
    phase = "completado"
    pct = 100.0
  elif current_wf is not None:
    if in_test:
      phase = f"WF ventana {current_wf}/{wf_windows - 1} backtest OOS"
    else:
      phase = f"WF ventana {current_wf}/{wf_windows - 1} hyperopt"
  elif completed_seeds >= seeds:
    phase = "WF pendiente"
  else:
    phase = f"semillas {completed_seeds}/{seeds}"

  return {
    "strategy": strategy,
    "run_id": run_id,
    "phase": phase,
    "pct_total": pct,
    "done_units": done_units,
    "total_units": total_units,
    "seeds_done": completed_seeds,
    "seeds_total": seeds,
    "wf_windows": wf_windows,
    "wf_train_done": wf_train_done,
    "wf_window_current": current_wf,
    "wf_epoch_current": active_epochs,
    "wf_epochs_per_window": epochs,
    "fthypt": fthypt_name,
  }


def format_line(data: dict) -> str:
  wf = data["wf_windows"]
  cur = data["wf_window_current"]
  ep = data["wf_epoch_current"]
  ep_max = data["wf_epochs_per_window"]
  wf_part = ""
  if cur is not None:
    wf_part = f" | WF {cur}/{wf - 1} epoch {ep}/{ep_max}"
  return (
    f"PROGRESO {data['pct_total']:5.1f}% — {data['phase']}"
    f" | semillas {data['seeds_done']}/{data['seeds_total']}"
    f"{wf_part}"
    f" | run={data['run_id']}"
  )


def main() -> None:
  parser = argparse.ArgumentParser(description="Progreso total validación")
  parser.add_argument("--strategy", default="MeanRevBB")
  parser.add_argument("--run-id", default="20260709_162954")
  parser.add_argument("--epochs", type=int, default=PROFILE_EPOCHS)
  parser.add_argument("--seeds", type=int, default=len(SEEDS))
  parser.add_argument("--json", action="store_true")
  args = parser.parse_args()

  data = compute_progress(
    strategy=args.strategy,
    run_id=args.run_id,
    epochs=args.epochs,
    seeds=args.seeds,
  )
  if args.json:
    print(json.dumps(data, indent=2))
  else:
    print(format_line(data))


if __name__ == "__main__":
  main()
