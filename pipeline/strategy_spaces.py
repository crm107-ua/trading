"""Espacios hyperopt permitidos por estrategia (solo buy/sell)."""

from __future__ import annotations

from pathlib import Path

STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "user_data" / "strategies"


def hyperopt_spaces_for(strategy: str) -> list[str]:
  """
  ``--spaces buy sell`` solo si la estrategia declara parámetros en sell.

  Evita el error de Freqtrade cuando sell está vacío (p.ej. GridDCA).
  """
  path = STRATEGIES_DIR / f"{strategy}.py"
  if not path.is_file():
    return ["buy"]
  text = path.read_text(encoding="utf-8")
  spaces = ["buy"]
  if 'space="sell"' in text or "space='sell'" in text:
    spaces.append("sell")
  return spaces
