"""Veredictos y criterios numéricos de validación (Fase 4)."""

from __future__ import annotations

from enum import Enum


class Verdict(str, Enum):
  ROBUSTA = "ROBUSTA"
  DUDOSA = "DUDOSA"
  SOBREAJUSTADA = "SOBREAJUSTADA"


# Umbrales por defecto — ajustables vía CLI en run_validation.
DEFAULT_MIN_TRADES_HYPEROPT = 100
DEFAULT_OOS_SHARPE_RATIO_MIN = 0.5  # OOS Sharpe >= 50% del IS
DEFAULT_WALK_FORWARD_EFFICIENCY_MIN = 0.5
DEFAULT_MAX_PARAM_DIVERGENCE = 0.25  # entre semillas de hyperopt
