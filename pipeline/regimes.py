"""Períodos etiquetados para backtests por régimen (Fase 4)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegimeWindow:
  """Ventana histórica con etiqueta de régimen dominante."""

  label: str
  timerange: str
  description: str


# Ventanas aproximadas en BTC spot — revisar con distribución real tras descarga extendida.
LABELED_REGIMES: tuple[RegimeWindow, ...] = (
  RegimeWindow("bull_2021", "20210101-20211130", "Rally post-COVID / ATH"),
  RegimeWindow("bear_2022", "20220101-20221231", "Bear market — LUNA/FTX"),
  RegimeWindow("range_2023", "20230101-20231031", "Recuperación lateral"),
  RegimeWindow("bull_2024", "20231101-20240320", "ETF / nuevo ATH parcial"),
  RegimeWindow("recent_2025", "20250101-", "Mercado reciente (completar tras descarga)"),
)
