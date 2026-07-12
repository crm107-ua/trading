#!/usr/bin/env python3
"""Progreso total de validación full (semillas + walk-forward)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from pipeline.hyperopt_resume import count_fthypt_epochs, list_strategy_fthypt_files
from pipeline.strategy_warmup import earliest_train_start
from pipeline.timerange_split import compute_is_oos_split, resolve_data_end
from pipeline.walk_forward import generate_walk_forward_windows
from pipeline.wf_resume import (
  evaluate_wf_adoption,
  load_wf_segment,
  timeranges_match_window,
)

REPORTS = ROOT / "user_data" / "validation_reports"
DATA_DIR = ROOT / "user_data" / "data" / "binance"
SEEDS = (42, 123, 456)
PROFILE_EPOCHS = 300
_TS_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+:\s*")
_PROGRESO_EPOCH = re.compile(r"epoch (\d+)/(\d+)")


def _out_log_path() -> Path:
  raw = os.environ.get("VALIDATION_OUT_LOG", "").strip()
  if raw:
    return Path(raw)
  return ROOT / "user_data" / "logs" / "pm2_meanrevbb.out.log"


def _newest_fthypt(strategy: str) -> Path | None:
  files = list_strategy_fthypt_files(strategy)
  if not files:
    return None
  return max(files, key=lambda p: p.stat().st_mtime)


def _wf_windows(strategy: str) -> list:
  data_end = resolve_data_end(DATA_DIR)
  split = compute_is_oos_split(f"20210101-{data_end.strftime('%Y%m%d')}", data_end=data_end)
  wf_train_min = earliest_train_start(split.full_start, strategy)
  return generate_walk_forward_windows(
    split.full_start,
    split.full_end,
    earliest_train_start=wf_train_min,
  )


def _wf_window_count(strategy: str) -> int:
  return len(_wf_windows(strategy))


def _wf_completed_from_disk(run_path: Path, strategy: str) -> int:
  """Nº de ventanas 0..K-1 con segment o train adoptable con timerange del plan."""
  params_dir = run_path / "params"
  windows = _wf_windows(strategy)
  completed = 0
  for w in windows:
    seg = load_wf_segment(params_dir, w.index)
    if seg and timeranges_match_window(w, train=seg.train, test=seg.test):
      completed = w.index + 1
      continue
    if (params_dir / f"wf{w.index}_train.json").is_file():
      decision = evaluate_wf_adoption(w, params_dir)
      if decision.adopted:
        completed = w.index + 1
        continue
      if "recuperación" in decision.reason or "legacy" in decision.reason:
        # pendiente de recuperar en próximo resume — no cuenta como hecha aún
        break
    break
  ck_path = run_path / "checkpoint.json"
  if ck_path.is_file():
    ck = json.loads(ck_path.read_text(encoding="utf-8"))
    for entry in ck.get("wf_windows_completed") or []:
      idx = int(entry["window"])
      plan = next((x for x in windows if x.index == idx), None)
      if plan and entry.get("train") == plan.train_timerange and entry.get("test") == plan.test_timerange:
        completed = max(completed, idx + 1)
  return completed


def _session_lines(log_path: Path) -> list[str]:
  """Líneas de la sesión activa (desde el último ``Reanudando``)."""
  if not log_path.is_file():
    return []
  lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
  start = 0
  for i, line in enumerate(lines):
    clean = _TS_PREFIX.sub("", line)
    if "Reanudando run_id=" in clean:
      start = i
  return lines[start:]


def _parse_orchestrator_wf(lines: list[str]) -> tuple[int | None, int, bool]:
  current: int | None = None
  completed: set[int] = set()
  in_test = False
  for line in lines:
    clean = _TS_PREFIX.sub("", line)
    m_train = re.search(r"ventana (\d+): train", clean)
    if m_train:
      current = int(m_train.group(1))
      in_test = False
    m_test = re.search(r"ventana (\d+): test", clean)
    if m_test:
      completed.add(int(m_test.group(1)))
      in_test = True
  return current, len(completed), in_test


def _wf_from_progreso(lines: list[str], *, epochs: int) -> tuple[int, int, int]:
  """
  Ventanas WF completadas, ventana actual y epoch en curso.

  Detecta fin de ventana cuando epoch cae de ~300 a ~1 en líneas PROGRESO.
  """
  completed = 0
  current_window = 0
  current_epoch = 0
  prev_epoch = 0
  seen = False

  for line in lines:
    if "PROGRESO" not in line:
      continue
    m = _PROGRESO_EPOCH.search(line)
    if not m:
      continue
    ep = int(m.group(1))
    seen = True
    if prev_epoch >= max(epochs - 5, 1) and ep <= 5 and prev_epoch > ep:
      completed += 1
      current_window = completed
    current_epoch = ep
    prev_epoch = ep

  if not seen:
    return 0, 0, 0
  return completed, current_window, current_epoch


def _estimate_eta_hours(
  *,
  done_units: float,
  total_units: float,
  session_lines: list[str],
) -> float | None:
  """ETA lineal desde la primera línea PROGRESO de la sesión actual."""
  first_ts: datetime | None = None
  first_done = 0.0
  last_ts: datetime | None = None

  for line in session_lines:
    if "PROGRESO" not in line:
      continue
    m_ts = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
    m_ep = _PROGRESO_EPOCH.search(line)
    if not m_ts or not m_ep:
      continue
    ts = datetime.fromisoformat(m_ts.group(1)).replace(tzinfo=timezone.utc)
    ep = int(m_ep.group(1))
    if first_ts is None:
      first_ts = ts
      first_done = ep  # aproximación baja al inicio WF
    last_ts = ts

  if first_ts is None or last_ts is None or last_ts <= first_ts:
    return None
  elapsed_h = (last_ts - first_ts).total_seconds() / 3600.0
  # Usar progreso de unidades WF en sesión: epoch acumulado aproximado
  wf_epochs_done = 0
  prev = 0
  for line in session_lines:
    if "PROGRESO" not in line:
      continue
    m = _PROGRESO_EPOCH.search(line)
    if not m:
      continue
    ep = int(m.group(1))
    if prev >= PROFILE_EPOCHS - 5 and ep <= 5 and prev > ep:
      wf_epochs_done += prev
    prev = ep
  wf_epochs_done += prev
  if wf_epochs_done <= first_done:
    return None
  rate = (wf_epochs_done - first_done) / elapsed_h
  remaining_epochs = total_units - done_units
  if rate <= 0:
    return None
  return remaining_epochs / rate


def compute_progress(
  *,
  strategy: str,
  run_id: str,
  epochs: int = PROFILE_EPOCHS,
  seeds: int = len(SEEDS),
  log_path: Path | None = None,
) -> dict:
  log_path = log_path or _out_log_path()
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
  seed_pct = round(100.0 * seed_done_units / total_units, 1) if total_units else 0.0

  wf_completed_disk = _wf_completed_from_disk(run_path, strategy)
  session = _session_lines(log_path)
  orch_window, _, in_test = _parse_orchestrator_wf(session)
  _, _, wf_epoch = _wf_from_progreso(session, epochs=epochs)

  wf_current = wf_completed_disk if wf_completed_disk < wf_windows else max(0, wf_windows - 1)
  if orch_window is not None and orch_window >= wf_completed_disk:
    wf_current = orch_window

  fthypt = _newest_fthypt(strategy)
  if fthypt and not in_test and wf_current < wf_windows:
    wf_epoch = max(wf_epoch, min(count_fthypt_epochs(fthypt), epochs))

  wf_done_units = min(wf_completed_disk * epochs + wf_epoch, wf_windows * epochs)
  wf_pct = round(100.0 * wf_done_units / total_units, 1) if total_units else 0.0

  done_units = seed_done_units + wf_done_units
  pct_total = round(100.0 * done_units / total_units, 1) if total_units else 0.0

  if run_path.joinpath("report.json").is_file():
    phase = "completado"
    pct_total = 100.0
    seed_pct = round(100.0 * seed_units / total_units, 1)
    wf_pct = round(100.0 * wf_units / total_units, 1)
  elif completed_seeds >= seeds:
    if in_test and orch_window is not None:
      phase = f"WF ventana {orch_window}/{wf_windows - 1} · backtest OOS"
    else:
      phase = f"WF ventana {wf_current}/{wf_windows - 1} · hyperopt"
  else:
    phase = f"semillas {completed_seeds}/{seeds}"

  eta_h = _estimate_eta_hours(
    done_units=done_units,
    total_units=total_units,
    session_lines=session,
  )
  eta_str = None
  if eta_h is not None and pct_total < 100:
    finish = datetime.now(timezone.utc) + timedelta(hours=eta_h)
    eta_str = finish.astimezone().strftime("%a %d %H:%M")

  return {
    "strategy": strategy,
    "run_id": run_id,
    "phase": phase,
    "pct_total": pct_total,
    "pct_seeds": seed_pct,
    "pct_wf": wf_pct,
    "done_units": int(done_units),
    "total_units": int(total_units),
    "seeds_done": completed_seeds,
    "seeds_total": seeds,
    "wf_windows": wf_windows,
    "wf_completed": wf_completed_disk,
    "wf_window_current": wf_current,
    "wf_epoch_current": wf_epoch,
    "wf_epochs_per_window": epochs,
    "fthypt": fthypt.name if fthypt else None,
    "eta_local": eta_str,
    "eta_hours": round(eta_h, 1) if eta_h else None,
  }


def _bar(pct: float, width: int = 20) -> str:
  filled = int(round(width * pct / 100.0))
  filled = max(0, min(width, filled))
  return "█" * filled + "░" * (width - filled)


def format_line(data: dict, *, style: str = "compact") -> str:
  wf = data["wf_windows"]
  cur = data["wf_window_current"]
  ep = data["wf_epoch_current"]
  ep_max = data["wf_epochs_per_window"]
  done_wf = data["wf_completed"]

  if style == "bar":
    eta = f" | ETA {data['eta_local']}" if data.get("eta_local") else ""
    return (
      f"{_bar(data['pct_total'])} {data['pct_total']:5.1f}% TOTAL"
      f" | semillas {data['pct_seeds']:.1f}%"
      f" | WF {data['pct_wf']:.1f}% (v{cur}/{wf - 1} ep {ep}/{ep_max}, hechas {done_wf})"
      f"{eta} | {data['run_id']}"
    )

  if style == "full":
    lines = [
      f"PROGRESO TOTAL {data['pct_total']:5.1f}%  {_bar(data['pct_total'], 24)}",
      (
        f"  semillas {data['seeds_done']}/{data['seeds_total']} "
        f"({data['pct_seeds']:.1f}% del total) · "
        f"WF ventana {cur}/{wf - 1} epoch {ep}/{ep_max} "
        f"({data['pct_wf']:.1f}% del total, {done_wf} ventanas hiperopt OK)"
      ),
      f"  fase: {data['phase']}",
    ]
    if data.get("eta_local"):
      lines.append(f"  ETA: {data['eta_local']} (~{data['eta_hours']}h)")
    lines.append(f"  run={data['run_id']}")
    return "\n".join(lines)

  # compact (default, compatible con grep PROGRESO en logs)
  eta = f" | ETA {data['eta_local']}" if data.get("eta_local") else ""
  return (
    f"PROGRESO {data['pct_total']:5.1f}% TOTAL"
    f" (sem {data['pct_seeds']:.1f}% + WF {data['pct_wf']:.1f}%)"
    f" — {data['phase']}"
    f" | v{cur}/{wf - 1} ep {ep}/{ep_max}"
    f" | {done_wf} ventanas OK"
    f"{eta} | run={data['run_id']}"
  )


def main() -> None:
  parser = argparse.ArgumentParser(description="Progreso total validación")
  parser.add_argument("--strategy", default="MeanRevBB")
  parser.add_argument("--run-id", default="20260709_162954")
  parser.add_argument("--epochs", type=int, default=PROFILE_EPOCHS)
  parser.add_argument("--seeds", type=int, default=len(SEEDS))
  parser.add_argument("--log", default="", help="Ruta out.log (override)")
  parser.add_argument("--json", action="store_true")
  parser.add_argument(
    "--format",
    choices=("compact", "bar", "full"),
    default="compact",
    help="Estilo de salida",
  )
  args = parser.parse_args()

  log_path = Path(args.log) if args.log else None
  data = compute_progress(
    strategy=args.strategy,
    run_id=args.run_id,
    epochs=args.epochs,
    seeds=args.seeds,
    log_path=log_path,
  )
  if args.json:
    print(json.dumps(data, indent=2))
  else:
    print(format_line(data, style=args.format))


if __name__ == "__main__":
  main()
