#!/usr/bin/env python3
"""
Robustez pre-validación de XSecMomentum (PC2, pandas puro).

Salidas en research/output/pc2_xsec_robustness.json:
- CAGR/Sharpe/DD por año calendario
- Distribución régimen BTC@1d y rendimiento con filtro BEAR
- Contribución PnL por par vs volumen medio (liquidez)
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from xsec_lab import (  # noqa: E402
  compute_btc_regime_daily,
  compute_metrics,
  load_closes_1d,
  log_returns,
  portfolio_return,
  weights_top_n_momentum,
)

LOCAL_DATADIR = ROOT / "research" / "data_local" / "binance"
FALLBACK_DATADIR = ROOT / "user_data" / "data" / "binance"
OUTPUT = ROOT / "research" / "output" / "pc2_xsec_robustness.json"

WINDOW = 14
TOP_N = 3
FEE = 0.001
FREQ = "W"

E2_PAIRS = [
  f"{a}/USDT"
  for a in (
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
]


@dataclass(frozen=True)
class PeriodMetrics:
  period: str
  cagr: float
  sharpe: float
  max_drawdown: float
  final_wealth: float
  days: int


def _resolve_datadir() -> Path:
  if LOCAL_DATADIR.is_dir() and any(LOCAL_DATADIR.glob("*-1d.feather")):
    return LOCAL_DATADIR
  return FALLBACK_DATADIR


def _load_volumes(datadir: Path, pairs: list[str]) -> pd.DataFrame:
  frames: dict[str, pd.Series] = {}
  for pair in pairs:
    path = datadir / f"{pair.replace('/', '_')}-1d.feather"
    if not path.is_file():
      continue
    df = pd.read_feather(path)
    if "volume" not in df.columns:
      continue
    s = df.set_index(pd.to_datetime(df["date"], utc=True))["volume"].sort_index()
    s.name = pair
    frames[pair] = s
  if not frames:
    return pd.DataFrame()
  return pd.DataFrame(frames).sort_index()


def _weights_with_bear_flat(
  prices: pd.DataFrame,
  as_of: pd.Timestamp,
  *,
  window: int,
  top_n: int,
  regime: pd.Series,
) -> pd.Series:
  reg = regime.reindex(prices.index).ffill()
  if as_of in reg.index and reg.loc[as_of] == "BEAR":
    return pd.Series(0.0, index=prices.columns)
  return weights_top_n_momentum(prices, as_of, window=window, top_n=top_n)


def _run_period(prices: pd.DataFrame, label: str, *, bear_filter: bool, regime: pd.Series) -> PeriodMetrics:
  if prices.empty or len(prices) < WINDOW + 5:
    return PeriodMetrics(label, 0.0, 0.0, 0.0, 1.0, 0)

  if bear_filter:

    def fn(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
      return _weights_with_bear_flat(p, t, window=WINDOW, top_n=TOP_N, regime=regime)

  else:

    def fn(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
      return weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)

  rets, _ = portfolio_return(prices, fn, FREQ, fee_per_rotation=FEE)
  m = compute_metrics(rets)
  return PeriodMetrics(label, m.cagr, m.sharpe, m.max_drawdown, m.final_wealth, len(prices))


def _pair_pnl_contribution(prices: pd.DataFrame, regime: pd.Series) -> pd.DataFrame:
  """Atribución aproximada: suma de retorno diario ponderado por par."""
  rets = log_returns(prices).fillna(0.0)
  weights_hist: list[pd.Series] = []
  rb_dates = set(
    pd.Series(1, index=prices.index)
    .groupby(pd.Grouper(freq="W-FRI"))
    .last()
    .dropna()
    .index
  )
  weights = _weights_with_bear_flat(prices, prices.index[0], window=WINDOW, top_n=TOP_N, regime=regime)
  weights = weights.reindex(prices.columns, fill_value=0.0)
  contrib = pd.Series(0.0, index=prices.columns)
  for i, dt in enumerate(prices.index):
    if i == 0:
      weights_hist.append(weights.copy())
      continue
    if dt in rb_dates:
      weights = _weights_with_bear_flat(prices, dt, window=WINDOW, top_n=TOP_N, regime=regime)
      weights = weights.reindex(prices.columns, fill_value=0.0)
    day = float((weights * rets.iloc[i]).sum())
    if day != 0 and weights.sum() > 0:
      contrib += weights * rets.iloc[i]
      asset_rets = rets.iloc[i]
      w_asset = weights * np.exp(asset_rets)
      total = w_asset.sum()
      if total > 0:
        weights = w_asset / total
    weights_hist.append(weights.copy())
  return contrib.sort_values(ascending=False)


def main() -> int:
  datadir = _resolve_datadir()
  prices = load_closes_1d(datadir, pairs=E2_PAIRS, start="2022-01-01")
  volumes = _load_volumes(datadir, E2_PAIRS)
  btc = prices["BTC/USDT"].dropna()
  regime = compute_btc_regime_daily(btc)

  annual: list[dict] = []
  for year in (2022, 2023, 2024, 2025, 2026):
    sl = slice(
      pd.Timestamp(f"{year}-01-01", tz="UTC"),
      pd.Timestamp(f"{year}-12-31", tz="UTC"),
    )
    sub = prices.loc[sl].dropna(how="all")
    if sub.empty:
      continue
    for bear_filter, suffix in ((False, "raw"), (True, "bear_flat")):
      m = _run_period(sub, f"{year}_{suffix}", bear_filter=bear_filter, regime=regime)
      annual.append(asdict(m))

  aligned_regime = regime.reindex(prices.index).ffill()
  regime_counts = aligned_regime.value_counts().to_dict()
  regime_days_pct = {k: round(v / len(aligned_regime.dropna()), 4) for k, v in regime_counts.items()}

  full_raw = _run_period(prices, "full_raw", bear_filter=False, regime=regime)
  full_bear = _run_period(prices, "full_bear_flat", bear_filter=True, regime=regime)

  contrib = _pair_pnl_contribution(prices, regime)
  vol_mean = volumes.mean() if not volumes.empty else pd.Series(dtype=float)
  liquidity_rows: list[dict] = []
  for pair in contrib.index:
    liquidity_rows.append(
      {
        "pair": pair,
        "log_pnl_contribution": float(contrib[pair]),
        "mean_daily_volume": float(vol_mean.get(pair, float("nan"))),
        "in_universe": pair in E2_PAIRS,
      }
    )
  liquidity_rows.sort(key=lambda r: r["log_pnl_contribution"], reverse=True)

  dexe = next((r for r in liquidity_rows if r["pair"] == "DEXE/USDT"), None)
  without_dexe_pairs = [p for p in E2_PAIRS if p != "DEXE/USDT"]
  prices_no_dexe = prices[without_dexe_pairs]
  no_dexe = _run_period(prices_no_dexe, "loo_exclude_dexe", bear_filter=True, regime=regime)

  payload = {
    "datadir": str(datadir.relative_to(ROOT)) if datadir.is_relative_to(ROOT) else str(datadir),
    "params": {"window": WINDOW, "top_n": TOP_N, "fee": FEE, "freq": FREQ},
    "annual_subperiods": annual,
    "btc_regime_1d": {
      "counts": regime_counts,
      "fraction": regime_days_pct,
      "note": "Clasificador pandas (ADX+EMA200); desviación documentada vs quant_core 4h en producción.",
    },
    "full_sample": {
      "without_bear_filter": asdict(full_raw),
      "with_bear_flat": asdict(full_bear),
      "bear_filter_delta_wealth": full_bear.final_wealth / full_raw.final_wealth
      if full_raw.final_wealth
      else None,
    },
    "leave_one_out_dexe": asdict(no_dexe),
    "pair_liquidity_contribution": liquidity_rows,
    "dexe_highlight": dexe,
  }

  OUTPUT.parent.mkdir(parents=True, exist_ok=True)
  OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
  print(f"Informe: {OUTPUT}")
  print(f"Datadir: {datadir}")
  print(f"Full bear_flat wealth: {full_bear.final_wealth:.3f} (raw {full_raw.final_wealth:.3f})")
  if dexe:
    print(
      f"DEXE: log_pnl={dexe['log_pnl_contribution']:.4f}, "
      f"mean_vol={dexe['mean_daily_volume']:.0f}"
    )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
