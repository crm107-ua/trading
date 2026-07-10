"""Warmup mínimo por estrategia — espejo de quant_core sin importar Freqtrade en host."""

from __future__ import annotations

from datetime import date, timedelta

REGIME_EMA_PERIOD = 200
REGIME_TF_MINUTES = 240  # 4h
STARTUP_CANDLE_MARGIN = 50

TF_MINUTES: dict[str, int] = {
  "1m": 1,
  "3m": 3,
  "5m": 5,
  "15m": 15,
  "30m": 30,
  "1h": 60,
  "2h": 120,
  "4h": 240,
  "1d": 1440,
}


def compute_startup_candle_count(timeframe: str) -> int:
  """Misma fórmula que ``user_data/strategies/quant_core.py``."""
  base_min = TF_MINUTES.get(timeframe, 60)
  return int(REGIME_EMA_PERIOD * (REGIME_TF_MINUTES / base_min)) + STARTUP_CANDLE_MARGIN


# Mantener sincronizado con user_data/strategies/*.py
STRATEGY_STARTUP: dict[str, tuple[int, str]] = {
  "MeanRevBB": (compute_startup_candle_count("15m"), "15m"),
  "RelativeMomentum": (compute_startup_candle_count("1h") + 30 * 24, "1h"),
}


def startup_candles_for_strategy(strategy: str) -> tuple[int, str]:
  if strategy in STRATEGY_STARTUP:
    return STRATEGY_STARTUP[strategy]
  return compute_startup_candle_count("1h"), "1h"


def warmup_days(strategy: str) -> int:
  candles, tf = startup_candles_for_strategy(strategy)
  minutes = candles * TF_MINUTES[tf]
  return (minutes + 1439) // 1440


def earliest_train_start(data_start: date, strategy: str) -> date:
  """Primer día en que una ventana WF puede entrenar con warmup disponible."""
  return data_start + timedelta(days=warmup_days(strategy))
