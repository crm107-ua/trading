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


@dataclass(frozen=True)
class AblationConfig:
  """Aproximaciones mecánicas Freqtrade (ablación acumulativa)."""

  discrete_slots: bool = False
  max_slots: int = 3
  bear_flat: bool = False
  stop_loss: float | None = None
  liquidity_exit_rebalance: bool = False


def _target_pairs_from_weights(weights: pd.Series) -> list[str]:
  w = weights.reindex(weights.index, fill_value=0.0).fillna(0.0)
  ranked = w[w > 0].sort_values(ascending=False)
  return [str(p) for p in ranked.index]


def portfolio_return_ablation(
  prices: pd.DataFrame,
  weights_fn: Callable[[pd.DataFrame, pd.Timestamp], pd.Series],
  rebalance_freq: RebalanceFreq,
  *,
  fee_per_rotation: float = 0.0,
  btc_regime: pd.Series | None = None,
  eligibility: pd.DataFrame | None = None,
  config: AblationConfig | None = None,
) -> tuple[pd.Series, float, dict[str, float]]:
  """
  Simulación de cartera con ablaciones Freqtrade.

  Si ``config`` es None o todas las flags son False, delega en ``portfolio_return``.
  Retorna (log_returns, turnover_medio, stats_extra).
  """
  cfg = config or AblationConfig()
  if not any(
    (
      cfg.discrete_slots,
      cfg.bear_flat,
      cfg.stop_loss is not None,
      cfg.liquidity_exit_rebalance,
    )
  ):
    rets, turnover = portfolio_return(prices, weights_fn, rebalance_freq, fee_per_rotation=fee_per_rotation)
    return rets, turnover, {"cash_drag_mean": 0.0, "weeks_incomplete_pct": 0.0}

  prices = prices.sort_index().ffill()
  rets = log_returns(prices).fillna(0.0)
  rb_dates = set(_rebalance_dates(prices.index, rebalance_freq))
  regime = btc_regime.reindex(prices.index).ffill() if btc_regime is not None else None
  elig = eligibility.reindex(prices.index) if eligibility is not None else None

  slots: list[tuple[str | None, float | None]] = [(None, None) for _ in range(cfg.max_slots)]
  port_log: list[float] = []
  dates_out: list[pd.Timestamp] = []
  turnovers: list[float] = []
  cash_drag_samples: list[float] = []
  incomplete_weeks = 0
  week_samples = 0

  slot_frac = 1.0 / cfg.max_slots

  def _filled_count() -> int:
    return sum(1 for p, _ in slots if p)

  def _invested_fraction() -> float:
    return _filled_count() * slot_frac

  def _close_slot(i: int) -> None:
    slots[i] = (None, None)

  def _close_all() -> None:
    for i in range(cfg.max_slots):
      _close_slot(i)

  def _pairs_held() -> set[str]:
    return {p for p, _ in slots if p}

  for i, dt in enumerate(prices.index):
    if i == 0:
      port_log.append(0.0)
      dates_out.append(dt)
      cash_drag_samples.append(1.0 - _invested_fraction())
      continue

    if cfg.stop_loss is not None:
      for si, (pair, entry) in enumerate(slots):
        if pair is None or entry is None:
          continue
        px = prices.loc[dt, pair]
        if pd.notna(px) and float(px) <= float(entry) * (1.0 + cfg.stop_loss):
          _close_slot(si)

    day_ret = 0.0
    for pair, _ in slots:
      if pair is None:
        continue
      day_ret += slot_frac * float(rets.loc[dt, pair])
    port_log.append(day_ret)
    dates_out.append(dt)
    cash_drag_samples.append(1.0 - _invested_fraction())

    if dt in rb_dates:
      week_samples += 1

      if cfg.bear_flat and regime is not None and str(regime.loc[dt]) == "BEAR":
        prev = _pairs_held()
        _close_all()
        turnover = 0.5 * len(prev) * slot_frac
        turnovers.append(turnover)
        port_log[-1] -= turnover * fee_per_rotation
        incomplete_weeks += 1
        continue

      target_w = weights_fn(prices, dt)
      targets = _target_pairs_from_weights(target_w)
      if cfg.liquidity_exit_rebalance and elig is not None and dt in elig.index:
        row = elig.loc[dt]
        targets = [p for p in targets if p in row.index and bool(row[p])]

      prev = _pairs_held()
      _close_all()
      for si, pair in enumerate(targets[: cfg.max_slots]):
        px = prices.loc[dt, pair]
        if pd.notna(px):
          slots[si] = (pair, float(px))

      if _filled_count() < cfg.max_slots:
        incomplete_weeks += 1

      new = _pairs_held()
      turnover = 0.5 * len(prev.symmetric_difference(new)) * slot_frac
      turnovers.append(turnover)
      port_log[-1] -= turnover * fee_per_rotation

  series = pd.Series(port_log, index=pd.DatetimeIndex(dates_out, tz="UTC"))
  avg_turnover = float(np.mean(turnovers)) if turnovers else 0.0
  stats = {
    "cash_drag_mean": float(np.mean(cash_drag_samples)) if cash_drag_samples else 0.0,
    "weeks_incomplete_pct": float(incomplete_weeks / week_samples) if week_samples else 0.0,
  }
  return series, avg_turnover, stats


def load_quote_volume_30d(
  pairs: list[str],
  index: pd.DatetimeIndex,
  *,
  datadir: Path | str = DEFAULT_DATADIR,
) -> pd.DataFrame:
  """Media móvil 30d del volumen quote (USDT), desplazada 1 día (causal)."""
  datadir = Path(datadir)
  frames: dict[str, pd.Series] = {}
  for pair in pairs:
    path = datadir / f"{pair.replace('/', '_')}-1d.feather"
    if not path.is_file():
      continue
    df = pd.read_feather(path)
    idx = pd.to_datetime(df["date"], utc=True)
    qv = df["volume"].astype(float) * df["close"].astype(float)
    qv.index = idx
    frames[pair] = qv.sort_index()
  qvol = pd.DataFrame(frames).sort_index()
  return qvol.rolling(30, min_periods=20).mean().shift(1).reindex(index)


def make_liquidity_masked_momentum(
  eligible: pd.DataFrame,
  *,
  window: int,
  top_n: int,
  stats: list[int] | None = None,
) -> Callable[[pd.DataFrame, pd.Timestamp], pd.Series]:
  """Top-N momentum restringido a pares elegibles en t (filtro 20M)."""

  def fn(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    hist = eligible.loc[:t]
    if hist.empty:
      return pd.Series(0.0, index=p.columns)
    last = hist.iloc[-1]
    cols = [c for c in p.columns if c in last.index and bool(last[c])]
    if stats is not None:
      stats.append(len(cols))
    if not cols:
      return pd.Series(0.0, index=p.columns)
    w_sub = weights_top_n_momentum(p[cols], t, window=window, top_n=top_n)
    w = pd.Series(0.0, index=p.columns)
    w.loc[w_sub.index] = w_sub
    return w

  return fn


def make_liquidity_masked_equal(
  eligible: pd.DataFrame,
) -> Callable[[pd.DataFrame, pd.Timestamp], pd.Series]:
  def fn(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    hist = eligible.loc[:t]
    if hist.empty:
      return pd.Series(0.0, index=p.columns)
    last = hist.iloc[-1]
    cols = [c for c in p.columns if c in last.index and bool(last[c]) and p.loc[:t, c].notna().any()]
    w = pd.Series(0.0, index=p.columns)
    if cols:
      w.loc[cols] = 1.0 / len(cols)
    return w

  return fn


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


# --- Reconciliación Freqtrade (13-D) ---


@dataclass(frozen=True)
class FidelityConfig:
  """Mecánicas Freqtrade acumulativas (motor_reconciliation)."""

  monday_rebalance: bool = False
  entry_next_open: bool = False
  fee_per_side: bool = False
  stop_on_low: float | None = None
  discrete_compound: bool = False
  pit_dexe: bool = False
  bear_filter: bool = True
  top_n: int = 3
  exit_rank_k: int = 4


def load_ohlcv_1d(
  datadir: Path | str = DEFAULT_DATADIR,
  pairs: list[str] | None = None,
  *,
  start: str | None = "2021-01-01",
  end: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
  """Carga OHLC 1d. Retorna (close, open, high, low) panels."""
  datadir = Path(datadir)
  closes: dict[str, pd.Series] = {}
  opens: dict[str, pd.Series] = {}
  highs: dict[str, pd.Series] = {}
  lows: dict[str, pd.Series] = {}
  for path in sorted(datadir.glob("*-1d.feather")):
    pair = column_to_pair(path.stem.replace("-1d", ""))
    if pairs is not None and pair not in pairs:
      continue
    df = pd.read_feather(path)
    if "date" not in df.columns:
      continue
    idx = pd.to_datetime(df["date"], utc=True)
    for col, store in (("close", closes), ("open", opens), ("high", highs), ("low", lows)):
      if col not in df.columns:
        continue
      s = pd.Series(df[col].astype(float).values, index=idx).sort_index()
      s.name = pair
      store[pair] = s
  if not closes:
    raise FileNotFoundError(f"sin OHLC 1d en {datadir}")
  out = tuple(
    pd.DataFrame(d).sort_index().loc[pd.Timestamp(start, tz="UTC") :]
    if start
    else pd.DataFrame(d).sort_index()
    for d in (closes, opens, highs, lows)
  )
  if end:
    out = tuple(df.loc[: pd.Timestamp(end, tz="UTC")] for df in out)
  return out  # type: ignore[return-value]


def momentum_rank_panel(
  close: pd.DataFrame,
  window: int,
  *,
  pit_dates: dict[str, pd.Timestamp] | None = None,
) -> pd.DataFrame:
  scores = momentum_score(close, window)
  if pit_dates:
    for pair, listing in pit_dates.items():
      if pair in scores.columns:
        scores.loc[scores.index < listing, pair] = np.nan
  return scores.rank(axis=1, method="min", ascending=False, na_option="keep")


def _rebalance_index(index: pd.DatetimeIndex, *, monday: bool) -> set[pd.Timestamp]:
  if monday:
    return set(index[index.weekday == 0])
  return set(_rebalance_dates(index, "W"))


def simulate_freqtrade_fidelity(
  close: pd.DataFrame,
  open_: pd.DataFrame,
  low: pd.DataFrame,
  ranks: pd.DataFrame,
  regime: pd.Series,
  config: FidelityConfig,
  *,
  initial_wallet: float = 10_000.0,
  fee_rate: float = 0.001,
) -> tuple[pd.Series, dict[str, float]]:
  """
  Simulador event-driven 3 slots alineado a XSecMomentum en Freqtrade.

  Retorna serie diaria de equity (USDT) y estadísticas auxiliares.
  """
  close = close.sort_index().ffill()
  open_ = open_.reindex(close.index).ffill()
  low = low.reindex(close.index).ffill()
  ranks = ranks.reindex(close.index)
  regime = regime.reindex(close.index).ffill()

  rb_signal_days = _rebalance_index(close.index, monday=config.monday_rebalance)
  pending_entries: list[str] = []
  slots: list[dict | None] = [None, None, None]
  wallet = float(initial_wallet)
  base_stake = initial_wallet / config.top_n
  equity_hist: list[float] = []
  dates_out: list[pd.Timestamp] = []
  n_stops = 0
  n_rotations = 0
  n_bear = 0
  startup_skip = 220

  def _slot_value(slot: dict, dt: pd.Timestamp) -> float:
    px = close.loc[dt, slot["pair"]]
    if pd.isna(px):
      return slot["stake"]
    return slot["stake"] * float(px) / slot["entry_price"]

  def _close_slot(i: int, dt: pd.Timestamp, price: float, reason: str) -> None:
    nonlocal wallet, n_stops, n_rotations, n_bear
    slot = slots[i]
    if not slot:
      return
    proceeds = slot["stake"] * price / slot["entry_price"]
    if config.fee_per_side:
      proceeds *= 1.0 - fee_rate
    wallet += proceeds
    if reason == "stop":
      n_stops += 1
    elif reason == "rotation":
      n_rotations += 1
    elif reason == "bear":
      n_bear += 1
    slots[i] = None

  def _open_slot(dt: pd.Timestamp, pair: str, *, check_bear: bool) -> None:
    nonlocal wallet
    if check_bear and config.bear_filter and str(regime.loc[dt]) == "BEAR":
      return
    if pair not in close.columns:
      return
    px = float(open_.loc[dt, pair])
    if pd.isna(px) or px <= 0:
      return
    free = next((j for j, s in enumerate(slots) if s is None), None)
    if free is None:
      return
    if config.discrete_compound:
      stake = wallet / config.top_n
    else:
      stake = base_stake
    if config.fee_per_side:
      stake *= 1.0 - fee_rate
    if stake <= 0:
      return
    wallet -= stake
    slots[free] = {"pair": pair, "entry_price": px, "stake": stake}

  def _exec_price(dt: pd.Timestamp, pair: str) -> float:
    if config.entry_next_open or config.monday_rebalance:
      return float(open_.loc[dt, pair])
    return float(close.loc[dt, pair])

  for i, dt in enumerate(close.index):
    if i < startup_skip:
      equity_hist.append(float(initial_wallet))
      dates_out.append(dt)
      continue

    # Entradas pendientes (open t+1 respecto a señal)
    if pending_entries and config.entry_next_open:
      for pair in pending_entries:
        _open_slot(dt, pair, check_bear=True)
      pending_entries = []

    # Stop intradía
    if config.stop_on_low is not None:
      for si, slot in enumerate(slots):
        if not slot:
          continue
        lo = low.loc[dt, slot["pair"]]
        if pd.notna(lo) and float(lo) <= slot["entry_price"] * (1.0 + config.stop_on_low):
          stop_px = slot["entry_price"] * (1.0 + config.stop_on_low)
          _close_slot(si, dt, stop_px, "stop")

    # Freqtrade 1d: señal lunes (cierre), ejecución martes open (100% trades en zip control).
    exec_rebalance = False
    signal_dt = dt
    if config.monday_rebalance and dt.weekday() == 1 and i > 0:
      prev = close.index[i - 1]
      if prev.weekday() == 0:
        exec_rebalance = True
        signal_dt = prev
    elif not config.monday_rebalance and dt in rb_signal_days:
      exec_rebalance = True

    if exec_rebalance:
      if config.bear_filter and str(regime.loc[signal_dt]) == "BEAR":
        for si in range(len(slots)):
          if slots[si]:
            px = _exec_price(dt, slots[si]["pair"])
            _close_slot(si, dt, px, "bear")
      else:
        row = ranks.loc[signal_dt] if signal_dt in ranks.index else None
        if row is not None:
          for si, slot in enumerate(slots):
            if not slot:
              continue
            rk = row.get(slot["pair"], np.nan)
            if pd.notna(rk) and float(rk) > config.exit_rank_k:
              px = _exec_price(dt, slot["pair"])
              _close_slot(si, dt, px, "rotation")
          held = {s["pair"] for s in slots if s}
          candidates = []
          for pair in close.columns:
            rk = row.get(pair, np.nan)
            if pd.notna(rk) and float(rk) <= config.top_n and pair not in held:
              candidates.append((float(rk), pair))
          candidates.sort()
          for _, pair in candidates[: config.top_n - len(held)]:
            if config.entry_next_open and not config.monday_rebalance:
              pending_entries.append(pair)
            else:
              _open_slot(dt, pair, check_bear=True)

    eq = wallet + sum(_slot_value(s, dt) for s in slots if s)
    equity_hist.append(eq)
    dates_out.append(dt)

  equity = pd.Series(equity_hist, index=pd.DatetimeIndex(dates_out, tz="UTC"))
  stats = {
    "final_wealth_mult": float(equity.iloc[-1] / initial_wallet),
    "n_stops": float(n_stops),
    "n_rotations": float(n_rotations),
    "n_bear": float(n_bear),
  }
  return equity, stats


def equity_to_log_returns(equity: pd.Series) -> pd.Series:
  eq = equity.replace(0, np.nan).ffill()
  return np.log(eq / eq.shift(1)).fillna(0.0)


def weekly_return_correlation(a: pd.Series, b: pd.Series) -> float:
  wa = a.resample("W-FRI").last().pct_change().dropna()
  wb = b.resample("W-FRI").last().pct_change().dropna()
  joined = pd.concat([wa, wb], axis=1, join="inner").dropna()
  if len(joined) < 5:
    return float("nan")
  return float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
