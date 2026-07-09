"""
Adopción de hyperopt parcial desde ``.fthypt`` (reanudación barata).

Cuando un run muere por timeout/corte de luz tras N-1/N epochs, el archivo en
``user_data/hyperopt_results/`` suele seguir siendo válido. Esta capa permite
exportar el mejor epoch sin re-ejecutar 300× hyperopt.

Activación: ``--adopt-partial-hyperopt`` o ``HYPEROPT_ADOPT_PARTIAL=1``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from pipeline.freqtrade_cli import base_config_args, run_freqtrade
from pipeline.params_manager import strategy_params_path

ROOT = Path(__file__).resolve().parents[1]
HYPEROPT_RESULTS = ROOT / "user_data" / "hyperopt_results"

FTHYPT_RE = re.compile(r"strategy_(.+?)_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.fthypt$")


def adopt_partial_enabled(cli_flag: bool) -> bool:
  env = os.environ.get("HYPEROPT_ADOPT_PARTIAL", "").strip().lower()
  if env in ("1", "true", "yes", "on"):
    return True
  if env in ("0", "false", "no", "off"):
    return False
  return cli_flag


def adopt_min_completion_ratio() -> float:
  return float(os.environ.get("HYPEROPT_ADOPT_MIN_RATIO", "0.95"))


def count_fthypt_epochs(path: Path) -> int:
  if not path.is_file():
    return 0
  count = 0
  with path.open(encoding="utf-8", errors="replace") as fh:
    for line in fh:
      if line.strip():
        count += 1
  return count


def list_strategy_fthypt_files(strategy: str) -> list[Path]:
  if not HYPEROPT_RESULTS.is_dir():
    return []
  out: list[Path] = []
  for path in HYPEROPT_RESULTS.glob(f"strategy_{strategy}_*.fthypt"):
    if path.is_file():
      out.append(path)
  return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def best_epoch_row(path: Path) -> dict | None:
  """Mejor fila por ``loss`` mínima (sin cargar todo el archivo en RAM)."""
  best: dict | None = None
  best_loss: float | None = None
  with path.open(encoding="utf-8", errors="replace") as fh:
    for line in fh:
      line = line.strip()
      if not line:
        continue
      try:
        row = json.loads(line)
      except json.JSONDecodeError:
        continue
      loss = row.get("loss")
      if loss is None:
        continue
      try:
        loss_f = float(loss)
      except (TypeError, ValueError):
        continue
      if best_loss is None or loss_f < best_loss:
        best_loss = loss_f
        best = row
  return best


def strategy_json_from_epoch_row(strategy: str, row: dict) -> dict:
  """Convierte una fila ``.fthypt`` al formato ``<Estrategia>.json`` de Freqtrade."""
  details = row.get("params_details") if isinstance(row.get("params_details"), dict) else {}
  not_opt = row.get("params_not_optimized") if isinstance(row.get("params_not_optimized"), dict) else {}
  params: dict = {}
  for key in ("roi", "stoploss", "trailing", "max_open_trades"):
    if key in not_opt:
      params[key] = not_opt[key]
  for space in ("buy", "sell"):
    block = details.get(space)
    if isinstance(block, dict):
      params[space] = block
  if not params.get("buy") and isinstance(row.get("params_dict"), dict):
    params["buy"] = {k: v for k, v in row["params_dict"].items() if k.startswith("buy_") or k in details.get("buy", {})}
  return {
    "strategy_name": strategy,
    "params": params,
    "ft_stratparam_v": 1,
  }


def run_hyperopt_list(strategy: str, fthypt_path: Path) -> tuple[bool, str]:
  """Valida el archivo con ``freqtrade hyperopt-list`` (Docker)."""
  try:
    rel = fthypt_path.relative_to(ROOT)
  except ValueError:
    return False, f"fuera de ROOT: {fthypt_path}"
  posix = rel.as_posix()
  args = [
    "hyperopt-list",
    *base_config_args(),
    "--strategy",
    strategy,
    "--strategy-path",
    "user_data/strategies",
    "--hyperopt-filename",
    posix,
    "--no-details",
  ]
  result = run_freqtrade(args, timeout=600)
  ok = result.returncode == 0 and "Epoch" in result.output
  return ok, result.output[-2000:]


@dataclass(frozen=True)
class PartialHyperoptAdoption:
  source_file: str
  epochs_done: int
  epochs_requested: int
  completion_ratio: float
  best_loss: float
  hyperopt_list_ok: bool
  note: str


def find_adoptable_fthypt(
  strategy: str,
  *,
  epochs_requested: int,
  min_ratio: float | None = None,
) -> tuple[Path, int] | None:
  ratio = adopt_min_completion_ratio() if min_ratio is None else min_ratio
  min_epochs = max(1, int(epochs_requested * ratio))
  for path in list_strategy_fthypt_files(strategy):
    done = count_fthypt_epochs(path)
    if done >= min_epochs:
      return path, done
  return None


def try_adopt_partial_hyperopt(
  strategy: str,
  *,
  epochs: int,
  seed: int,
  validate_with_list: bool = True,
) -> PartialHyperoptAdoption | None:
  """
  Si hay un ``.fthypt`` parcial suficientemente completo, escribe ``<Estrategia>.json``.

  No borra el archivo fuente. Devuelve ``None`` si no aplica.
  """
  candidate = find_adoptable_fthypt(strategy, epochs_requested=epochs)
  if candidate is None:
    return None
  path, done = candidate
  ratio = done / epochs if epochs else 0.0
  min_ratio = adopt_min_completion_ratio()
  if ratio < min_ratio:
    return None

  row = best_epoch_row(path)
  if row is None:
    return None

  list_ok = True
  list_tail = ""
  if validate_with_list:
    list_ok, list_tail = run_hyperopt_list(strategy, path)
    if not list_ok:
      return None

  payload = strategy_json_from_epoch_row(strategy, row)
  dest = strategy_params_path(strategy)
  dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")

  loss = float(row.get("loss") or 0.0)
  note = (
    f"adopted_partial_hyperopt seed={seed} file={path.name} "
    f"epochs={done}/{epochs} ratio={ratio:.3f} loss={loss:.4f}"
  )
  if list_tail and not list_ok:
    note += f"\nhyperopt-list:\n{list_tail}"

  return PartialHyperoptAdoption(
    source_file=path.name,
    epochs_done=done,
    epochs_requested=epochs,
    completion_ratio=ratio,
    best_loss=loss,
    hyperopt_list_ok=list_ok,
    note=note,
  )
