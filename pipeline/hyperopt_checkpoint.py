"""Archivo de artefactos hyperopt por semilla (reanudación barata)."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HYPEROPT_RESULTS = ROOT / "user_data" / "hyperopt_results"


def archive_hyperopt_results(dest: Path) -> list[str]:
  """
  Copia user_data/hyperopt_results/ a dest/ tras completar una semilla.

  Devuelve nombres de archivos archivados (vacío si no había nada).
  """
  if not HYPEROPT_RESULTS.is_dir():
    return []
  dest.mkdir(parents=True, exist_ok=True)
  archived: list[str] = []
  for item in sorted(HYPEROPT_RESULTS.iterdir()):
    if not item.is_file():
      continue
    target = dest / item.name
    shutil.copy2(item, target)
    archived.append(item.name)
  return archived
