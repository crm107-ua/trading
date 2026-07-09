"""Gestión explícita de ``<Estrategia>.json`` — fallo-en-vacío #5 de Fase 4."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "user_data" / "strategies"

PARAM_LOG_RE = re.compile(
  r"Strategy Parameter(?:\(default\))?:\s+(\S+)\s*=\s*([^\s]+)"
)


def strategy_params_path(strategy: str) -> Path:
  return STRATEGIES_DIR / f"{strategy}.json"


def params_file_exists(strategy: str) -> bool:
  return strategy_params_path(strategy).is_file()


def read_strategy_params(strategy: str) -> dict | None:
  path = strategy_params_path(strategy)
  if not path.is_file():
    return None
  return json.loads(path.read_text(encoding="utf-8"))


def clear_strategy_params(strategy: str) -> dict | None:
  """Elimina el json de parámetros. Devuelve el contenido previo si existía."""
  path = strategy_params_path(strategy)
  if not path.is_file():
    return None
  content = json.loads(path.read_text(encoding="utf-8"))
  path.unlink()
  return content


def install_strategy_params(strategy: str, source: Path) -> Path:
  """Copia parámetros archivados al path que Freqtrade carga en silencio."""
  dest = strategy_params_path(strategy)
  shutil.copy2(source, dest)
  return dest


def archive_strategy_params(
  strategy: str,
  archive_dir: Path,
  label: str,
  *,
  source: Path | None = None,
) -> Path | None:
  """Archiva params actuales (o ``source``) como ``{label}.json``."""
  archive_dir.mkdir(parents=True, exist_ok=True)
  src = source or strategy_params_path(strategy)
  if not src.is_file():
    return None
  dest = archive_dir / f"{label}.json"
  shutil.copy2(src, dest)
  meta = {
    "strategy": strategy,
    "label": label,
    "archived_at": datetime.now(timezone.utc).isoformat(),
    "source": str(src),
  }
  dest.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
  return dest


def flatten_params_export(data: dict) -> dict[str, object]:
  """Aplana ``params.buy`` / ``params.sell`` a un dict comparables."""
  flat: dict[str, object] = {}
  params = data.get("params") if isinstance(data, dict) else None
  if isinstance(params, dict):
    for space in ("buy", "sell"):
      block = params.get(space)
      if isinstance(block, dict):
        for key, value in block.items():
          flat[f"{space}_{key}" if not key.startswith(space) else key] = value
  return flat


def parse_loaded_params_from_log(log: str) -> dict[str, str]:
  """Extrae parámetros que Freqtrade anunció al cargar la estrategia."""
  loaded: dict[str, str] = {}
  for match in PARAM_LOG_RE.finditer(log):
    loaded[match.group(1)] = match.group(2).rstrip(",")
  return loaded


def verify_params_loaded(
  expected_file: Path,
  log_output: str,
  *,
  allow_defaults: bool = False,
) -> tuple[bool, list[str]]:
  """
  Compara params archivados vs log de backtest/hyperopt.

  Si ``allow_defaults`` es False, falla si el log muestra ``(default)``.
  """
  issues: list[str] = []
  if not expected_file.is_file():
    return False, [f"archivo esperado no existe: {expected_file}"]

  expected_raw = json.loads(expected_file.read_text(encoding="utf-8"))
  expected = flatten_params_export(expected_raw)
  if not expected:
    issues.append("archivo de params sin bloque params.buy/sell")
    return False, issues

  loaded = parse_loaded_params_from_log(log_output)
  if not loaded:
    issues.append("log sin Strategy Parameter — no auditable qué cargó Freqtrade")
    return False, issues

  if not allow_defaults and "Strategy Parameter(default)" in log_output:
    issues.append("se cargaron defaults; se esperaban params optimizados")

  for key, exp_val in expected.items():
    # Freqtrade log usa nombres sin prefijo buy_ a veces — probar ambas formas
    candidates = {key, key.replace("buy_", ""), key.replace("sell_", "")}
    found = None
    for cand in candidates:
      if cand in loaded:
        found = loaded[cand]
        break
    if found is None:
      issues.append(f"param esperado no aparece en log: {key}")
      continue
    if str(found) != str(exp_val):
      issues.append(f"param {key}: esperado {exp_val}, log={found}")

  return len(issues) == 0, issues


def param_divergence(params_a: dict, params_b: dict) -> float:
  """Distancia relativa media entre dos exports de hyperopt (0 = idénticos)."""
  flat_a = flatten_params_export(params_a)
  flat_b = flatten_params_export(params_b)
  keys = set(flat_a) & set(flat_b)
  if not keys:
    return 1.0
  deltas: list[float] = []
  for key in keys:
    a, b = flat_a[key], flat_b[key]
    try:
      fa, fb = float(a), float(b)
      denom = max(abs(fa), abs(fb), 1e-9)
      deltas.append(abs(fa - fb) / denom)
    except (TypeError, ValueError):
      deltas.append(0.0 if a == b else 1.0)
  return sum(deltas) / len(deltas)
