#!/usr/bin/env python3
"""
R1 — Funding rates como señal/filtro (intentos #11 y #12, pre-registrados).

Dato de FUTUROS (Binance USDT-perp, 8h) usado como señal para operar SPOT.

#11 — Funding extremo (> p90 rolling 90d, percentil FIJO) = sobrecalentamiento:
     retornos spot forward 1/3/7d condicionados peores que incondicionales.
     Criterio: t-stat > 2 (evento < incondicional) en AMBAS mitades (agregado).
     Si existe: medir veto de entrada en XSecMomentum (una regla, sin params nuevos).

#12 — Funding <= 0 como señal contraria: top-3 momentum restringido a pares con
     funding <= 0 al rebalanceo vs top-3 libre.
     Criterio: mejora Sharpe B en AMBAS mitades Y >= 60% semanas con cartera completa.

Salidas: research/output/r1_funding.json + r1_funding_curves.png
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from xsec_lab import (  # noqa: E402
  compute_metrics,
  load_closes_1d,
  log_returns,
  portfolio_return,
  weights_top_n_momentum,
)

DATADIR = ROOT / "research" / "data_local" / "binance"
FUNDING_DIR = ROOT / "research" / "data_local" / "funding"
OUTPUT_JSON = ROOT / "research" / "output" / "r1_funding.json"
OUTPUT_PNG = ROOT / "research" / "output" / "r1_funding_curves.png"

WINDOW = 14
TOP_N = 3
FEE = 0.001
FREQ = "W"
PCTL = 0.90          # fijo, pre-registrado — no optimizar
ROLL_DAYS = 90
HORIZONS = (1, 3, 7)

E2_PAIRS = [
  f"{a}/USDT"
  for a in (
    "AAVE", "ADA", "BNB", "BTC", "DEXE", "DOGE", "ETH", "LTC",
    "NEAR", "SKL", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC",
  )
]

HALVES = {
  "2021-23": ("2021-01-01", "2023-12-31"),
  "2024-26": ("2024-01-01", "2026-12-31"),
}


def load_funding_daily(pairs: list[str]) -> pd.DataFrame:
  """Funding medio diario por par (media de los 3 pagos de 8h)."""
  frames: dict[str, pd.Series] = {}
  for pair in pairs:
    path = FUNDING_DIR / f"{pair.replace('/', '_')}-funding.feather"
    if not path.is_file():
      continue
    df = pd.read_feather(path)
    s = df.set_index(pd.to_datetime(df["funding_time"], utc=True))["funding_rate"].sort_index()
    daily = s.resample("1D").mean()
    daily.name = pair
    frames[pair] = daily
  return pd.DataFrame(frames).sort_index()


def rolling_p90_mask(funding: pd.DataFrame) -> pd.DataFrame:
  """True donde funding del día > percentil 90 causal de los 90 días previos."""
  # shift(1): el umbral usa solo historia estrictamente anterior
  thr = funding.rolling(ROLL_DAYS, min_periods=60).quantile(PCTL).shift(1)
  return funding > thr


def _welch_t(a: pd.Series, b: pd.Series) -> float:
  if len(a) < 5 or len(b) < 20:
    return float("nan")
  se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
  if se < 1e-12:
    return 0.0
  return float((a.mean() - b.mean()) / se)


def _forward_sum(log_r: pd.Series, h: int) -> pd.Series:
  """Retorno log forward h días (t+1 .. t+h), causal para condicionar en t."""
  return log_r.shift(-1).rolling(h).sum().shift(-(h - 1))


def event_study_funding_high(
  prices: pd.DataFrame, hot_mask: pd.DataFrame
) -> tuple[list[dict], dict]:
  log_r = log_returns(prices)
  rows: list[dict] = []
  agg: dict = {}
  # Agregado: pool de todos los pares
  for half, (start, stop) in HALVES.items():
    sl = slice(pd.Timestamp(start, tz="UTC"), pd.Timestamp(stop, tz="UTC"))
    for h in HORIZONS:
      evt_all: list[pd.Series] = []
      pool_all: list[pd.Series] = []
      for col in prices.columns:
        if col not in hot_mask.columns:
          continue
        r = log_r[col].dropna()
        fwd = _forward_sum(r, h)
        mask = hot_mask[col].reindex(r.index).fillna(False)
        evt = fwd[mask].loc[sl].dropna()
        pool = fwd.loc[sl].dropna()
        if len(evt) >= 5 and len(pool) >= 20:
          rows.append(
            {
              "pair": col,
              "half": half,
              "horizon": h,
              "n_events": int(len(evt)),
              "mean_event": float(evt.mean()),
              "mean_uncond": float(pool.mean()),
              "diff": float(evt.mean() - pool.mean()),
              "tstat": _welch_t(evt, pool),
            }
          )
        evt_all.append(evt)
        pool_all.append(pool)
      evt_c = pd.concat(evt_all) if evt_all else pd.Series(dtype=float)
      pool_c = pd.concat(pool_all) if pool_all else pd.Series(dtype=float)
      agg[f"{half}_h{h}"] = {
        "n_events": int(len(evt_c)),
        "n_pool": int(len(pool_c)),
        "mean_event": float(evt_c.mean()) if len(evt_c) else None,
        "mean_uncond": float(pool_c.mean()) if len(pool_c) else None,
        "diff": float(evt_c.mean() - pool_c.mean()) if len(evt_c) else None,
        "tstat": _welch_t(evt_c, pool_c),
      }
  return rows, agg


def _metrics(prices: pd.DataFrame, fn, fee: float) -> dict:
  rets, turnover = portfolio_return(prices, fn, FREQ, fee_per_rotation=fee)
  return asdict(compute_metrics(rets, turnover=turnover))


def _weights_restricted(
  prices: pd.DataFrame,
  as_of: pd.Timestamp,
  *,
  eligible_mask: pd.DataFrame,
  count_full: list[int] | None = None,
) -> pd.Series:
  """Top-3 momentum solo entre pares elegibles según máscara diaria (as-of causal)."""
  mask_hist = eligible_mask.loc[:as_of]
  if mask_hist.empty:
    return pd.Series(0.0, index=prices.columns)
  last = mask_hist.iloc[-1]
  cols = [c for c in prices.columns if c in last.index and bool(last[c])]
  if not cols:
    if count_full is not None:
      count_full.append(0)
    return pd.Series(0.0, index=prices.columns)
  sub = prices[cols]
  w_sub = weights_top_n_momentum(sub, as_of, window=WINDOW, top_n=TOP_N)
  if count_full is not None:
    count_full.append(int((w_sub > 0).sum()))
  w = pd.Series(0.0, index=prices.columns)
  w.loc[w_sub.index] = w_sub
  return w


def _run_restricted_suite(
  prices: pd.DataFrame, eligible: pd.DataFrame, label: str
) -> dict:
  """Cartera restringida por máscara vs libre — B, muestra completa + mitades."""
  out: dict = {"label": label}

  def fn_free(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    return weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)

  positions_log: list[int] = []

  def fn_restricted(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    return _weights_restricted(p, t, eligible_mask=eligible, count_full=positions_log)

  for scope, pr in (
    ("full", prices),
    *((half, prices.loc[slice(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC"))]) for half, (a, b) in HALVES.items()),
  ):
    positions_log.clear()
    out[scope] = {
      "free_B": _metrics(pr, fn_free, FEE),
      "restricted_B": _metrics(pr, fn_restricted, FEE),
      "restricted_A": _metrics(pr, fn_restricted, 0.0),
      "weeks_full_portfolio_pct": (
        float(np.mean([1.0 if n >= TOP_N else 0.0 for n in positions_log])) if positions_log else 0.0
      ),
      "n_rebalances": len(positions_log),
    }
  return out


def main() -> int:
  prices = load_closes_1d(DATADIR, pairs=E2_PAIRS, start="2021-01-01")
  funding = load_funding_daily(E2_PAIRS)
  funding = funding.reindex(prices.index).ffill(limit=3)

  hot = rolling_p90_mask(funding)

  # ---- #11: event study funding extremo
  rows_11, agg_11 = event_study_funding_high(prices, hot)
  crit_11 = {}
  for half in HALVES:
    # criterio agregado: t < -2 (evento peor que incondicional) en algún horizonte, consistente
    crit_11[half] = {
      f"h{h}": {
        "tstat": agg_11[f"{half}_h{h}"]["tstat"],
        "passes_t2_negative": bool(
          agg_11[f"{half}_h{h}"]["tstat"] is not None
          and not np.isnan(agg_11[f"{half}_h{h}"]["tstat"])
          and agg_11[f"{half}_h{h}"]["tstat"] < -2.0
        ),
      }
      for h in HORIZONS
    }
  passes_11 = {
    f"h{h}": all(crit_11[half][f"h{h}"]["passes_t2_negative"] for half in HALVES)
    for h in HORIZONS
  }

  # ---- #11b: veto de entrada (solo informativo si #11 falla)
  not_hot = ~hot.fillna(False)
  veto_suite = _run_restricted_suite(prices, not_hot, "xsec_veto_funding_hot")

  # ---- #12: restricción funding <= 0
  neg_mask = funding.le(0.0)
  neg_suite = _run_restricted_suite(prices, neg_mask, "xsec_only_funding_neg")
  crit_12 = {
    "sharpe_improves_2021_23": bool(
      neg_suite["2021-23"]["restricted_B"]["sharpe"] > neg_suite["2021-23"]["free_B"]["sharpe"]
    ),
    "sharpe_improves_2024_26": bool(
      neg_suite["2024-26"]["restricted_B"]["sharpe"] > neg_suite["2024-26"]["free_B"]["sharpe"]
    ),
    "weeks_full_portfolio_pct_full": neg_suite["full"]["weeks_full_portfolio_pct"],
    "weeks_full_ge_60pct": bool(neg_suite["full"]["weeks_full_portfolio_pct"] >= 0.60),
  }
  crit_12["passes"] = bool(
    crit_12["sharpe_improves_2021_23"]
    and crit_12["sharpe_improves_2024_26"]
    and crit_12["weeks_full_ge_60pct"]
  )

  results = {
    "note": "Funding de FUTUROS (USDT-perp Binance) como senal para SPOT. p90 rolling 90d fijo.",
    "funding_coverage": {
      c: {
        "first_valid": str(funding[c].first_valid_index()),
        "n_days": int(funding[c].notna().sum()),
      }
      for c in funding.columns
    },
    "intent_11": {
      "hypothesis": "funding > p90 rolling 90d -> retornos spot forward peores",
      "criterion": "t < -2 agregado en AMBAS mitades (percentil fijo 0.90)",
      "aggregate": agg_11,
      "criterion_by_half": crit_11,
      "passes_by_horizon": passes_11,
      "passes_any_horizon": bool(any(passes_11.values())),
      "per_pair_rows": rows_11,
      "veto_on_xsec_informative": veto_suite,
    },
    "intent_12": {
      "hypothesis": "top-3 momentum restringido a funding <= 0 mejora al libre",
      "criterion": "mejora Sharpe B en ambas mitades Y >=60% semanas cartera completa",
      "suite": neg_suite,
      "criterion_eval": crit_12,
    },
  }

  OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
  OUTPUT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")

  # Curvas comparativas (B)
  import matplotlib

  matplotlib.use("Agg")
  import matplotlib.pyplot as plt

  def fn_free(p, t):
    return weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)

  def fn_veto(p, t):
    return _weights_restricted(p, t, eligible_mask=not_hot)

  def fn_neg(p, t):
    return _weights_restricted(p, t, eligible_mask=neg_mask)

  fig, ax = plt.subplots(figsize=(11, 5))
  for label, fn in (
    ("top-3 libre (B)", fn_free),
    ("veto funding>p90 (B) — #11", fn_veto),
    ("solo funding<=0 (B) — #12", fn_neg),
  ):
    rets, _ = portfolio_return(prices, fn, FREQ, fee_per_rotation=FEE)
    ax.plot(rets.index, np.exp(rets.cumsum()), label=label, linewidth=1.2)
  ax.set_yscale("log")
  ax.set_ylabel("wealth (log)")
  ax.set_title("R1 — XSecMomentum con reglas de funding (#11 veto / #12 restriccion)")
  ax.legend()
  ax.grid(True, alpha=0.3)
  fig.tight_layout()
  fig.savefig(OUTPUT_PNG, dpi=120)
  plt.close(fig)

  print(f"JSON: {OUTPUT_JSON}")
  print(f"PNG:  {OUTPUT_PNG}")
  print("#11 agregado (t-stats):")
  for k, v in agg_11.items():
    print(f"  {k}: t={v['tstat']:.2f} n_evt={v['n_events']}" if v["tstat"] == v["tstat"] else f"  {k}: sin datos")
  print(f"#11 pasa (ambas mitades, por horizonte): {passes_11}")
  print(
    f"#12: Sharpe libre/restr 21-23: {neg_suite['2021-23']['free_B']['sharpe']:.2f}/"
    f"{neg_suite['2021-23']['restricted_B']['sharpe']:.2f} | 24-26: "
    f"{neg_suite['2024-26']['free_B']['sharpe']:.2f}/{neg_suite['2024-26']['restricted_B']['sharpe']:.2f} | "
    f"semanas cartera completa: {neg_suite['full']['weeks_full_portfolio_pct']:.0%} -> "
    f"{'PASA' if crit_12['passes'] else 'FALLA'}"
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
