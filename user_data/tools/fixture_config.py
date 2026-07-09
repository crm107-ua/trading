"""Configuración compartida para backtests programáticos sobre fixtures."""

from __future__ import annotations

from pathlib import Path

from freqtrade.configuration import Configuration


def fixture_datadir(root: Path | None = None) -> Path:
  """Ruta absoluta al datadir de fixtures (incluye subcarpeta exchange)."""
  base = root or Path("/freqtrade")
  return base / "user_data" / "fixtures" / "data" / "binance"


def default_fixture_config_files(root: Path | None = None) -> list[str]:
  base = root or Path("/freqtrade")
  return [
    str(base / "user_data/config/base.json"),
    str(base / "user_data/config/backtest.json"),
    str(base / "user_data/config/backtest_fixtures.json"),
  ]


def load_fixture_backtest_config(
  config_files: list[str] | None = None,
  *,
  root: Path | None = None,
) -> dict:
  """
  Carga config de backtest y fuerza datadir de fixtures.

  Freqtrade ignora ``datadir`` en JSON si no se pasa ``--datadir`` por CLI:
  ``create_datadir`` usa ``user_data/data`` por defecto. Hay que asignar la
  ruta completa (con ``binance``) tras ``get_config()``.
  """
  base = root or Path("/freqtrade")
  files = config_files or default_fixture_config_files(base)
  config = Configuration.from_files(files)
  if hasattr(config, "get_config"):
    config = config.get_config()
  config["datadir"] = fixture_datadir(base)
  return config
