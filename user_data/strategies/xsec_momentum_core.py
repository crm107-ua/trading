"""
Funciones puras — momentum cross-sectional 1d (XSecMomentum, intento #10).

Espejo del motor ``research/xsec_lab.py`` con ranking point-in-time:
un par sin ``window`` velas de historia queda con score NaN y no rankea.
"""

from __future__ import annotations

import pandas as pd

XSEC_ENTER_TAG = "xsec_momentum"
XSEC_EXIT_ROTATION_TAG = "xsec_rotation_exit"
XSEC_EXIT_BEAR_TAG = "xsec_bear_flat"
XSEC_EXIT_LIQUIDITY_TAG = "xsec_liquidity_exit"

# Filtro liquidez 20M (intento #13 / XSecMomentum20M) — constantes congeladas, no hyperopt
LIQUIDITY_WINDOW = 30
LIQUIDITY_MIN_PERIODS = 20
LIQUIDITY_THRESHOLD_USDT = 20_000_000.0

# Universo E2 (16 pares USDT, historial >= 2022, sin stablecoins/apalancados)
XSEC_UNIVERSE_ASSETS = (
  "AAVE",
  "ADA",
  "BNB",
  "BTC",
  "DEXE",
  "DOGE",
  "ETH",
  "LTC",
  "NEAR",
  "SKL",
  "SOL",
  "TRX",
  "UNI",
  "XLM",
  "XRP",
  "ZEC",
)

REBALANCE_WEEKDAY = 0  # lunes — no optimizable (E4 descartó estacionalidad)


def momentum_score(close: pd.Series, window: int) -> pd.Series:
  """Retorno lookback causal: usa cierres hasta t-1 inclusive."""
  if window <= 0:
    raise ValueError("window debe ser > 0")
  prior = close.shift(1)
  base = close.shift(1 + window)
  return prior / base - 1.0


def rank_universe(scores: dict[str, pd.Series]) -> pd.DataFrame:
  """Ranking cross-sectional: 1 = mayor momentum; NaN = sin historial PIT."""
  if not scores:
    return pd.DataFrame()
  frame = pd.DataFrame(scores)
  return frame.rank(axis=1, method="min", ascending=False, na_option="keep")


def top_n_mask(rank: pd.Series, n: int) -> pd.Series:
  if n <= 0:
    raise ValueError("n debe ser > 0")
  valid = rank.notna()
  return valid & (rank <= n)


def rebalance_day_mask(dates: pd.Series, *, weekday: int = REBALANCE_WEEKDAY) -> pd.Series:
  dts = pd.to_datetime(dates, utc=True)
  if isinstance(dts, pd.DatetimeIndex):
    wd = dts.weekday
  else:
    wd = dts.dt.weekday
  return pd.Series(wd == weekday, index=dates.index)


def rebalance_entry_mask(
  rank: pd.Series,
  dates: pd.Series,
  *,
  top_n: int,
  weekday: int = REBALANCE_WEEKDAY,
) -> pd.Series:
  """Entrada solo en día de rebalanceo para pares en top-N."""
  rb = rebalance_day_mask(dates, weekday=weekday)
  return top_n_mask(rank, top_n) & rb


def rotation_exit_on_rebalance(
  rank: pd.Series,
  dates: pd.Series,
  *,
  exit_rank_k: int,
  weekday: int = REBALANCE_WEEKDAY,
) -> pd.Series:
  """Salida por rotación: rebalanceo + rank > K (banda muerta)."""
  if exit_rank_k <= 0:
    raise ValueError("exit_rank_k debe ser > 0")
  rb = rebalance_day_mask(dates, weekday=weekday)
  return rb & (rank > float(exit_rank_k))


def bear_flat_on_rebalance(
  regime: pd.Series,
  dates: pd.Series,
  *,
  bear_value: str,
  weekday: int = REBALANCE_WEEKDAY,
) -> pd.Series:
  """En rebalanceo con régimen BEAR → cerrar posiciones (ir plano)."""
  rb = rebalance_day_mask(dates, weekday=weekday)
  return rb & (regime.astype(str) == bear_value)


def universe_close_column(asset: str) -> str:
  return f"close_{asset.lower()}"


def universe_quote_volume_column(asset: str) -> str:
  return f"quote_vol_{asset.lower()}"


def quote_volume_usdt(volume: pd.Series, close: pd.Series) -> pd.Series:
  """Volumen quote USDT ≈ volume (base) × close — misma aprox. que ``r2_liquidity_filter.py``."""
  return volume.astype(float) * close.astype(float)


def liquidity_eligibility_mask(
  quote_volume: pd.Series,
  *,
  window: int = LIQUIDITY_WINDOW,
  threshold: float = LIQUIDITY_THRESHOLD_USDT,
  min_periods: int = LIQUIDITY_MIN_PERIODS,
) -> pd.Series:
  """
  Elegible en t si la media móvil ``window`` del vol. quote, desplazada 1 día (causal: hasta t-1),
  supera ``threshold`` USDT/día.
  """
  rolling_mean = quote_volume.rolling(window, min_periods=min_periods).mean().shift(1)
  return rolling_mean > threshold


def liquidity_exit_on_rebalance(
  eligible: pd.Series,
  dates: pd.Series,
  *,
  weekday: int = REBALANCE_WEEKDAY,
) -> pd.Series:
  """En rebalanceo, salir si el par deja de ser elegible (equiv. a desaparecer del top en research)."""
  rb = rebalance_day_mask(dates, weekday=weekday)
  return rb & (~eligible.fillna(False))


def build_pair_ranks(
  dataframe: pd.DataFrame,
  *,
  asset_columns: dict[str, str],
  window: int,
  asset_eligibility: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
  scores: dict[str, pd.Series] = {}
  for asset, col in asset_columns.items():
    if col not in dataframe.columns:
      continue
    score = momentum_score(dataframe[col], window)
    if asset_eligibility and asset in asset_eligibility:
      score = score.where(asset_eligibility[asset])
    scores[asset] = score
  return rank_universe(scores)
