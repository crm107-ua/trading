"""
Laboratorio cross-sectional en pandas puro — sin Freqtrade.

Motor mínimo de cartera + métricas de triaje para research/ (E1–E4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATADIR = ROOT / "user_data" / "data" / "binance"

RebalanceFreq = Literal["W", "M"]


@dataclass(frozen=True)
class PortfolioMetrics:
  cagr: float
  sharpe: float
  max_drawdown: float
  turnover: float
  final_wealth: float


def pair_to_column(pair: str) -> str:
  return pair.replace("/", "_")


def column_to_pair(column: str) -> str:
  return column.replace("_", "/")


def load_closes_1d(
  datadir: Path | str = DEFAULT_DATADIR,
  pairs: list[str] | None = None,
  *,
  start: str | None = "2021-01-01",
  end: str | None = None,
) -> pd.DataFrame:
  """Carga cierres 1d desde feather (solo lectura). Índice UTC, columnas = par USDT."""
  datadir = Path(datadir)
  frames: dict[str, pd.Series] = {}
  for path in sorted(datadir.glob("*-1d.feather")):
    pair = column_to_pair(path.stem.replace("-1d", ""))
    if pairs is not None and pair not in pairs:
      continue
    df = pd.read_feather(path)
    if "date" not in df.columns or "close" not in df.columns:
      continue
    s = df.set_index(pd.to_datetime(df["date"], utc=True))["close"].sort_index()
    s.name = pair
    frames[pair] = s
  if not frames:
    raise FileNotFoundError(f"sin datos 1d en {datadir}")
  out = pd.DataFrame(frames).sort_index()
  if start:
    out = out.loc[pd.Timestamp(start, tz="UTC") :]
  if end:
    out = out.loc[: pd.Timestamp(end, tz="UTC")]
  return out.dropna(how="all", axis=1)


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
  return np.log(prices / prices.shift(1))


def momentum_score(prices: pd.DataFrame, window: int) -> pd.DataFrame:
  """Retorno lookback sobre cierres, causal (termina en t-1)."""
  prior = prices.shift(1)
  base = prices.shift(1 + window)
  return prior / base - 1.0


def weights_top_n_momentum(
  prices: pd.DataFrame,
  as_of: pd.Timestamp,
  *,
  window: int,
  top_n: int,
) -> pd.Series:
  """Pesos equal-weight top-N por momentum en ``as_of`` (solo historia ≤ as_of)."""
  hist = prices.loc[:as_of]
  if len(hist) < window + 2:
    return pd.Series(0.0, index=prices.columns)
  scores = momentum_score(hist, window).iloc[-1]
  valid = scores.dropna()
  if valid.empty:
    return pd.Series(0.0, index=prices.columns)
  top = valid.nlargest(min(top_n, len(valid))).index
  w = pd.Series(0.0, index=prices.columns)
  w.loc[top] = 1.0 / len(top)
  return w


def weights_equal(prices: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
  hist = prices.loc[:as_of].dropna(how="all", axis=1)
  cols = [c for c in prices.columns if c in hist.columns and hist[c].notna().any()]
  if not cols:
    return pd.Series(0.0, index=prices.columns)
  w = pd.Series(0.0, index=prices.columns)
  w.loc[cols] = 1.0 / len(cols)
  return w


def weights_btc_only(prices: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
  w = pd.Series(0.0, index=prices.columns)
  btc = "BTC/USDT"
  if btc in prices.columns and as_of in prices.index and pd.notna(prices.loc[as_of, btc]):
    w[btc] = 1.0
  elif btc in prices.columns:
    sub = prices.loc[:as_of, btc].dropna()
    if not sub.empty:
      w[btc] = 1.0
  return w


def _rebalance_dates(index: pd.DatetimeIndex, freq: RebalanceFreq) -> pd.DatetimeIndex:
  ser = pd.Series(1, index=index)
  if freq == "W":
    groups = ser.groupby(pd.Grouper(freq="W-FRI")).last()
  else:
    groups = ser.groupby(pd.Grouper(freq="ME")).last()
  return pd.DatetimeIndex(groups.dropna().index)


def portfolio_return(
  prices: pd.DataFrame,
  weights_fn: Callable[[pd.DataFrame, pd.Timestamp], pd.Series],
  rebalance_freq: RebalanceFreq,
  *,
  fee_per_rotation: float = 0.0,
) -> tuple[pd.Series, float]:
  """
  Retornos log diarios de cartera + turnover medio por evento de rebalanceo.

  ``fee_per_rotation``: fracción aplicada a turnover (0.001 = 0.1% × turnover).
  """
  prices = prices.sort_index().ffill()
  rets = log_returns(prices).fillna(0.0)
  rb_dates = set(_rebalance_dates(prices.index, rebalance_freq))

  weights = weights_fn(prices, prices.index[0])
  weights = weights.reindex(prices.columns, fill_value=0.0).fillna(0.0)
  port_log: list[float] = []
  dates_out: list[pd.Timestamp] = []
  turnovers: list[float] = []

  for i, dt in enumerate(prices.index):
    if i == 0:
      port_log.append(0.0)
      dates_out.append(dt)
      continue

    if dt in rb_dates:
      target = weights_fn(prices, dt)
      target = target.reindex(prices.columns, fill_value=0.0).fillna(0.0)
      turnover = 0.5 * float((target - weights).abs().sum())
      turnovers.append(turnover)
      cost = turnover * fee_per_rotation
      weights = target
    else:
      cost = 0.0

    day_ret = float((weights * rets.iloc[i]).sum())
    port_log.append(day_ret - cost)
    dates_out.append(dt)

    # Drift
    if day_ret != 0 and weights.sum() > 0:
      asset_rets = rets.iloc[i]
      w_asset = weights * np.exp(asset_rets)
      total = w_asset.sum()
      if total > 0:
        weights = w_asset / total

  series = pd.Series(port_log, index=pd.DatetimeIndex(dates_out, tz="UTC"))
  avg_turnover = float(np.mean(turnovers)) if turnovers else 0.0
  return series, avg_turnover


def compute_metrics(daily_log_returns: pd.Series, *, turnover: float = 0.0) -> PortfolioMetrics:
  r = daily_log_returns.dropna()
  if r.empty:
    return PortfolioMetrics(0.0, 0.0, 0.0, turnover, 1.0)
  wealth = np.exp(r.cumsum())
  total_years = (r.index[-1] - r.index[0]).days / 365.25
  final = float(wealth.iloc[-1])
  cagr = float(final ** (1 / total_years) - 1) if total_years > 0 else 0.0
  vol = float(r.std())
  sharpe = float(r.mean() / vol * np.sqrt(252)) if vol > 1e-12 else 0.0
  dd = wealth / wealth.cummax() - 1.0
  max_dd = float(dd.min())
  return PortfolioMetrics(cagr, sharpe, max_dd, turnover, final)


def run_strategy_grid(
  prices: pd.DataFrame,
  *,
  windows: list[int],
  top_ns: list[int],
  freqs: list[RebalanceFreq],
  fee: float,
) -> pd.DataFrame:
  rows: list[dict] = []
  for window in windows:
    for top_n in top_ns:
      for freq in freqs:
        fn = lambda p, t, w=window, n=top_n: weights_top_n_momentum(p, t, window=w, top_n=n)
        rets_a, to_a = portfolio_return(prices, fn, freq, fee_per_rotation=0.0)
        rets_b, to_b = portfolio_return(prices, fn, freq, fee_per_rotation=fee)
        ma = compute_metrics(rets_a, turnover=to_a)
        mb = compute_metrics(rets_b, turnover=to_b)
        rows.append(
          {
            "window": window,
            "top_n": top_n,
            "freq": freq,
            "cagr_a": ma.cagr,
            "sharpe_a": ma.sharpe,
            "max_dd_a": ma.max_drawdown,
            "turnover_a": ma.turnover,
            "cagr_b": mb.cagr,
            "sharpe_b": mb.sharpe,
            "max_dd_b": mb.max_drawdown,
            "turnover_b": mb.turnover,
            "final_b": mb.final_wealth,
          }
        )
  return pd.DataFrame(rows)


def run_benchmarks(
  prices: pd.DataFrame,
  freqs: list[RebalanceFreq],
  fee: float,
) -> pd.DataFrame:
  rows: list[dict] = []
  for label, fn in (
    ("equal_weight", weights_equal),
    ("btc_buy_hold", weights_btc_only),
  ):
    for freq in freqs:
      rets_a, to_a = portfolio_return(prices, fn, freq, fee_per_rotation=0.0)
      rets_b, to_b = portfolio_return(prices, fn, freq, fee_per_rotation=fee)
      ma = compute_metrics(rets_a, turnover=to_a)
      mb = compute_metrics(rets_b, turnover=to_b)
      rows.append(
        {
          "strategy": label,
          "freq": freq,
          "cagr_a": ma.cagr,
          "sharpe_a": ma.sharpe,
          "max_dd_a": ma.max_drawdown,
          "cagr_b": mb.cagr,
          "sharpe_b": mb.sharpe,
          "max_dd_b": mb.max_drawdown,
          "turnover_b": mb.turnover,
          "final_b": mb.final_wealth,
        }
      )
  return pd.DataFrame(rows)


# --- Régimen BTC (reimplementado en pandas, sin importar strategies/) ---

def compute_btc_regime_daily(btc_close: pd.Series, *, adx_period: int = 14) -> pd.Series:
  """BULL / BEAR / RANGE simplificado en 1d (misma lógica que quant_core)."""
  close = btc_close.dropna()
  ema200 = close.ewm(span=200, adjust=False).mean()
  high = close
  low = close
  tr = pd.concat(
    [
      high - low,
      (high - close.shift(1)).abs(),
      (low - close.shift(1)).abs(),
    ],
    axis=1,
  ).max(axis=1)
  atr = tr.ewm(span=adx_period, adjust=False).mean()
  up = close.diff().clip(lower=0)
  dn = (-close.diff()).clip(lower=0)
  plus_di = 100 * up.ewm(span=adx_period, adjust=False).mean() / atr.replace(0, np.nan)
  minus_di = 100 * dn.ewm(span=adx_period, adjust=False).mean() / atr.replace(0, np.nan)
  dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
  adx = dx.ewm(span=adx_period, adjust=False).mean()
  adx_threshold = 25.0
  regime = pd.Series("RANGE", index=close.index)
  trend = adx >= adx_threshold
  regime.loc[trend & (close > ema200)] = "BULL"
  regime.loc[trend & (close <= ema200)] = "BEAR"
  return regime


def _forward_log_sum(log_r: pd.Series, h: int) -> pd.Series:
  out = pd.Series(np.nan, index=log_r.index)
  vals = log_r.values
  for i in range(len(vals) - h):
    out.iloc[i] = float(np.sum(vals[i + 1 : i + 1 + h]))
  return out


def event_study_extremes(
  prices: pd.DataFrame,
  btc_regime: pd.Series,
  *,
  sigma_window: int = 30,
  horizons: tuple[int, ...] = (1, 3, 7),
) -> pd.DataFrame:
  """Retorno forward medio tras eventos ±2σ vs incondicional, por mitad temporal."""
  log_r = log_returns(prices)
  rows: list[dict] = []
  for col in prices.columns:
    r = log_r[col].dropna()
    mu = r.rolling(sigma_window).mean()
    sd = r.rolling(sigma_window).std()
    z = (r - mu) / sd.replace(0, np.nan)
    for side, mask_fn in (("low_2sigma", lambda z: z < -2), ("high_2sigma", lambda z: z > 2)):
      for h in horizons:
        fwd_h = _forward_log_sum(r, h)
        events = z[mask_fn(z)].index
        evt_vals = fwd_h.reindex(events).dropna()
        all_vals = fwd_h.dropna()
        for half, (start, stop) in (
          ("2021-23", ("2021-01-01", "2023-12-31")),
          ("2024-26", ("2024-01-01", "2026-12-31")),
        ):
          sl = slice(pd.Timestamp(start, tz="UTC"), pd.Timestamp(stop, tz="UTC"))
          ev = evt_vals.loc[sl]
          pool = all_vals.loc[sl]
          if len(ev) < 5 or len(pool) < 20:
            continue
          diff = ev.mean() - pool.mean()
          se = np.sqrt(ev.var(ddof=1) / len(ev) + pool.var(ddof=1) / len(pool))
          tstat = diff / se if se > 1e-12 else 0.0
          rows.append(
            {
              "pair": col,
              "side": side,
              "horizon": h,
              "half": half,
              "n_events": len(ev),
              "mean_event": float(ev.mean()),
              "mean_uncond": float(pool.mean()),
              "diff": float(diff),
              "tstat": float(tstat),
            }
          )
  return pd.DataFrame(rows)


def weekday_seasonality(prices: pd.DataFrame) -> pd.DataFrame:
  log_r = log_returns(prices)
  rows: list[dict] = []
  for col in prices.columns:
    r = log_r[col].dropna()
    for half, (start, stop) in (
      ("2021-23", ("2021-01-01", "2023-12-31")),
      ("2024-26", ("2024-01-01", "2026-12-31")),
    ):
      sl = slice(pd.Timestamp(start, tz="UTC"), pd.Timestamp(stop, tz="UTC"))
      sub = r.loc[sl]
      if sub.empty:
        continue
      overall = sub.mean()
      for wd in range(7):
        day_r = sub[sub.index.weekday == wd]
        if len(day_r) < 10:
          continue
        diff = day_r.mean() - overall
        se = np.sqrt(day_r.var(ddof=1) / len(day_r) + sub.var(ddof=1) / len(sub))
        tstat = diff / se if se > 1e-12 else 0.0
        rows.append(
          {
            "pair": col,
            "weekday": wd,
            "half": half,
            "mean_wd": day_r.mean(),
            "mean_all": overall,
            "tstat": tstat,
            "n": len(day_r),
          }
        )
  return pd.DataFrame(rows)


def save_equity_curve(
  daily_log_returns: pd.Series,
  path: Path,
  *,
  title: str = "",
) -> None:
  import matplotlib.pyplot as plt

  path.parent.mkdir(parents=True, exist_ok=True)
  wealth = np.exp(daily_log_returns.cumsum())
  fig, ax = plt.subplots(figsize=(10, 4))
  ax.plot(wealth.index, wealth.values, linewidth=1.2)
  ax.set_title(title or path.stem)
  ax.set_ylabel("wealth (start=1)")
  ax.grid(True, alpha=0.3)
  fig.tight_layout()
  fig.savefig(path, dpi=120)
  plt.close(fig)


def list_available_1d_pairs(datadir: Path | str = DEFAULT_DATADIR) -> list[dict]:
  datadir = Path(datadir)
  out: list[dict] = []
  for path in sorted(datadir.glob("*-1d.feather")):
    df = pd.read_feather(path, columns=["date"])
    dates = pd.to_datetime(df["date"], utc=True)
    pair = column_to_pair(path.stem.replace("-1d", ""))
    out.append(
      {
        "pair": pair,
        "start": str(dates.min().date()),
        "rows": len(df),
      }
    )
  return out


def pair_listing_dates(datadir: Path | str = DEFAULT_DATADIR) -> dict[str, pd.Timestamp]:
  """Primera vela 1d disponible por par (proxy listing para controles PIT)."""
  return {
    x["pair"]: pd.Timestamp(x["start"], tz="UTC")
    for x in list_available_1d_pairs(datadir)
  }


def weights_top_n_momentum_pit(
  prices: pd.DataFrame,
  as_of: pd.Timestamp,
  *,
  window: int,
  top_n: int,
  listing_dates: dict[str, pd.Timestamp],
  min_history_days: int | None = None,
) -> pd.Series:
  """
  Top-N momentum con universo point-in-time: solo pares listados antes de ``as_of``.

  ``min_history_days``: días mínimos desde listing hasta ``as_of`` (default ``window+1``).
  """
  lookback = min_history_days if min_history_days is not None else window + 1
  cutoff = as_of - pd.Timedelta(days=lookback)
  eligible = [
    c
    for c in prices.columns
    if c in listing_dates and listing_dates[c] <= cutoff and prices.loc[:as_of, c].notna().sum() >= window + 2
  ]
  if not eligible:
    return pd.Series(0.0, index=prices.columns)
  sub = prices[eligible]
  w_sub = weights_top_n_momentum(sub, as_of, window=window, top_n=top_n)
  w = pd.Series(0.0, index=prices.columns)
  w.loc[w_sub.index] = w_sub
  return w


def weights_top_n_momentum_excluding(
  prices: pd.DataFrame,
  as_of: pd.Timestamp,
  *,
  window: int,
  top_n: int,
  exclude: set[str],
) -> pd.Series:
  """Top-N momentum omitiendo pares en ``exclude``."""
  cols = [c for c in prices.columns if c not in exclude]
  if not cols:
    return pd.Series(0.0, index=prices.columns)
  sub = prices[cols]
  w_sub = weights_top_n_momentum(sub, as_of, window=window, top_n=top_n)
  w = pd.Series(0.0, index=prices.columns)
  w.loc[w_sub.index] = w_sub
  return w


def dominant_pair_full_sample(prices: pd.DataFrame, window: int) -> str | None:
  """Par con mayor momentum en la última fecha (proxy del 'ganador' retrospectivo)."""
  scores = momentum_score(prices, window).iloc[-1].dropna()
  if scores.empty:
    return None
  return str(scores.idxmax())


@dataclass(frozen=True)
class BiasControlResult:
  label: str
  final_wealth: float
  max_drawdown: float
  sharpe: float
  cagr: float
  n_pairs_at_end: int


def run_bias_control(
  prices: pd.DataFrame,
  *,
  window: int,
  top_n: int,
  freq: RebalanceFreq,
  fee: float,
  listing_dates: dict[str, pd.Timestamp],
  label: str,
  mode: Literal["baseline", "pit", "exclude_dominant"],
) -> BiasControlResult:
  exclude_dom: set[str] = set()
  if mode == "exclude_dominant":
    dom = dominant_pair_full_sample(prices, window)
    if dom:
      exclude_dom = {dom}

  def fn(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    if mode == "pit":
      return weights_top_n_momentum_pit(
        p, t, window=window, top_n=top_n, listing_dates=listing_dates
      )
    if mode == "exclude_dominant":
      return weights_top_n_momentum_excluding(
        p, t, window=window, top_n=top_n, exclude=exclude_dom
      )
    return weights_top_n_momentum(p, t, window=window, top_n=top_n)

  rets, turnover = portfolio_return(prices, fn, freq, fee_per_rotation=fee)
  m = compute_metrics(rets, turnover=turnover)
  last_w = fn(prices, prices.index[-1])
  return BiasControlResult(
    label=label,
    final_wealth=m.final_wealth,
    max_drawdown=m.max_drawdown,
    sharpe=m.sharpe,
    cagr=m.cagr,
    n_pairs_at_end=int((last_w > 0).sum()),
  )
