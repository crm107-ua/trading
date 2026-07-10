"""
Funciones puras para momentum relativo cross-sectional (sin Freqtrade).

Convención causal del score (momentum_score):
  En la vela operativa t (p. ej. 1h), el score usa solo cierres hasta t-1 inclusive.
  La señal se evalúa al cierre de t y la ejecución ocurre en t+1 (Freqtrade estándar).
  Implementación: close.shift(1) / close.shift(1 + window) - 1.
"""

from __future__ import annotations

import pandas as pd

REL_MOMENTUM_ENTER_TAG = "rel_momentum"
REL_MOMENTUM_EXIT_TAG = "rel_momentum_exit"

UNIVERSE_ASSETS = ("BTC", "ETH", "BNB", "SOL", "XRP")


def momentum_score(close: pd.Series, window: int) -> pd.Series:
  """
  Retorno acumulado sobre ``window`` velas, causal (sin incluir el cierre de t).

  NaN mientras no hay histórico suficiente.
  """
  if window <= 0:
    raise ValueError("window debe ser > 0")
  prior = close.shift(1)
  base = close.shift(1 + window)
  return prior / base - 1.0


def rank_universe(scores: dict[str, pd.Series]) -> pd.DataFrame:
  """
  Ranking cross-sectional por vela: 1 = par más fuerte.

  Pares con NaN en el score quedan fuera del ranking (NaN, no rank 0).
  """
  if not scores:
    return pd.DataFrame()
  frame = pd.DataFrame(scores)
  return frame.rank(axis=1, method="min", ascending=False, na_option="keep")


def top_n_mask(rank: pd.Series, n: int) -> pd.Series:
  """True si el par está en el top-N (rank <= n) y el rank es válido."""
  if n <= 0:
    raise ValueError("n debe ser > 0")
  valid = rank.notna()
  return valid & (rank <= n)


def rotation_entry_mask(
  rank: pd.Series,
  *,
  top_n: int,
  confirm_bars: int,
) -> pd.Series:
  """
  Entrada tras histéresis: el par debe permanecer en top-N ``confirm_bars`` velas seguidas.

  Defensa anti-whipsaw #1 — evita rotar en el primer tick del ranking.
  En RelativeMomentum usar ``rotation_entry_mask_daily`` (confirmación en días, no horas).
  """
  if confirm_bars <= 0:
    raise ValueError("confirm_bars debe ser > 0")
  in_top = top_n_mask(rank, top_n)
  return in_top.rolling(confirm_bars, min_periods=confirm_bars).min().astype(bool)


def rotation_entry_mask_daily(
  rank: pd.Series,
  dates: pd.Series,
  *,
  top_n: int,
  confirm_days: int,
) -> pd.Series:
  """
  Histéresis en velas **diarias** del ranking (1-5 días), luego ffill a la serie operativa.

  El ranking cross-sectional se calcula sobre cierres 1d; medir confirm_bars en 1h con ffill
  haría la histéresis decorativa (24 velas idénticas por día).
  """
  if confirm_days <= 0:
    raise ValueError("confirm_days debe ser > 0")
  dts = pd.to_datetime(dates, utc=True)
  day = dts.floor("D") if isinstance(dts, pd.DatetimeIndex) else dts.dt.floor("D")
  # Ranking diario solo con el cierre del día ya conocido: .last() por día y shift(1)
  # evita lookahead intradía (truncation check fallaba con full=1 trunc=0).
  daily_rank = rank.groupby(day).last().shift(1)
  daily_entry = rotation_entry_mask(daily_rank, top_n=top_n, confirm_bars=confirm_days)
  day_series = pd.Series(day, index=rank.index)
  return day_series.map(daily_entry).fillna(False).astype(bool)


def rotation_exit_mask(
  rank: pd.Series,
  *,
  exit_rank_k: int,
) -> pd.Series:
  """
  Salida cuando el par cae fuera del top-K (banda muerta).

  Defensa anti-whipsaw #2 — con top_n=1 y exit_rank_k=2, rank 2 no dispara salida;
  solo rank 3+ (K+1 en espíritu de banda muerta). Requiere exit_rank_k >= top_n.
  """
  if exit_rank_k <= 0:
    raise ValueError("exit_rank_k debe ser > 0")
  return rank > float(exit_rank_k)


def universe_daily_close_column(asset: str) -> str:
  """Nombre de columna tras merge_informative_pair(..., suffix=asset.lower())."""
  return f"close_{asset.lower()}"


def build_pair_ranks(
  dataframe: pd.DataFrame,
  *,
  asset_columns: dict[str, str],
  window: int,
) -> pd.DataFrame:
  """Construye scores y ranking para todos los pares del universo."""
  scores: dict[str, pd.Series] = {}
  for asset, col in asset_columns.items():
    if col not in dataframe.columns:
      continue
    scores[asset] = momentum_score(dataframe[col], window)
  return rank_universe(scores)
