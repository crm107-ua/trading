#!/usr/bin/env python3
"""
R0 — Control del intento #10 (no es intento nuevo).

Pre-registro (docs/hypothesis_registry.md fila 10-R0, escrito antes de calcular):
el efecto E2 es robusto a ilíquidos si top-3 w14 semanal, excluyendo DEXE y ZEC
simultáneamente, mantiene en versión B (fee 0.1%/rotación):
  wealth > equal-weight del universo reducido  Y  wealth > 2.0x

Salidas: research/output/r0_exdexe_exzec.json + r0_exdexe_exzec.png
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
  weights_equal,
  weights_btc_only,
  weights_top_n_momentum,
)

DATADIR = ROOT / "research" / "data_local" / "binance"
OUTPUT_JSON = ROOT / "research" / "output" / "r0_exdexe_exzec.json"
OUTPUT_PNG = ROOT / "research" / "output" / "r0_exdexe_exzec.png"

WINDOW = 14
TOP_N = 3
FEE = 0.001
FREQ = "W"
EXCLUDED = ("DEXE/USDT", "ZEC/USDT")
WEALTH_THRESHOLD = 2.0  # pre-fijado en el registro antes de calcular

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


def _metrics_dict(prices: pd.DataFrame, weights_fn, fee: float) -> dict:
  rets, turnover = portfolio_return(prices, weights_fn, FREQ, fee_per_rotation=fee)
  m = compute_metrics(rets, turnover=turnover)
  return asdict(m)


def _momentum_fn(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
  return weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)


def _slice(prices: pd.DataFrame, half: str) -> pd.DataFrame:
  start, stop = HALVES[half]
  sl = slice(pd.Timestamp(start, tz="UTC"), pd.Timestamp(stop, tz="UTC"))
  return prices.loc[sl].dropna(how="all")


def _suite(prices: pd.DataFrame, label: str) -> dict:
  out: dict = {"label": label, "n_pairs": len(prices.columns)}
  for fee, ver in ((0.0, "A"), (FEE, "B")):
    out[f"momentum_{ver}"] = _metrics_dict(prices, _momentum_fn, fee)
    out[f"equal_weight_{ver}"] = _metrics_dict(prices, weights_equal, fee)
    out[f"btc_bh_{ver}"] = _metrics_dict(prices, weights_btc_only, fee)
  return out


def _load_quote_volumes(pairs: list[str]) -> pd.DataFrame:
  """Volumen USDT aproximado = volumen base x close, por día."""
  frames: dict[str, pd.Series] = {}
  for pair in pairs:
    path = DATADIR / f"{pair.replace('/', '_')}-1d.feather"
    if not path.is_file():
      continue
    df = pd.read_feather(path)
    idx = pd.to_datetime(df["date"], utc=True)
    s = (df["volume"].astype(float) * df["close"].astype(float))
    s.index = idx
    s.name = pair
    frames[pair] = s.sort_index()
  return pd.DataFrame(frames).sort_index()


def _pair_contribution(prices: pd.DataFrame) -> pd.Series:
  """Suma de retorno log diario ponderado por par (misma mecánica que portfolio_return)."""
  prices = prices.sort_index().ffill()
  rets = log_returns(prices).fillna(0.0)
  rb = set(
    pd.Series(1, index=prices.index).groupby(pd.Grouper(freq="W-FRI")).last().dropna().index
  )
  weights = _momentum_fn(prices, prices.index[0]).reindex(prices.columns, fill_value=0.0)
  contrib = pd.Series(0.0, index=prices.columns)
  for i, dt in enumerate(prices.index):
    if i == 0:
      continue
    if dt in rb:
      weights = _momentum_fn(prices, dt).reindex(prices.columns, fill_value=0.0)
    day_contrib = weights * rets.iloc[i]
    contrib += day_contrib
    day_ret = float(day_contrib.sum())
    if day_ret != 0 and weights.sum() > 0:
      w_asset = weights * np.exp(rets.iloc[i])
      total = w_asset.sum()
      if total > 0:
        weights = w_asset / total
  return contrib


def main() -> int:
  full = load_closes_1d(DATADIR, pairs=E2_PAIRS, start="2021-01-01")
  reduced_pairs = [p for p in E2_PAIRS if p not in EXCLUDED]
  reduced = full[reduced_pairs]

  results: dict = {
    "control_of": "intent #10 (10-R0, no cuenta como intento nuevo)",
    "excluded": list(EXCLUDED),
    "params": {"window": WINDOW, "top_n": TOP_N, "fee_B": FEE, "freq": FREQ},
    "criterion": {
      "wealth_B_gt_equal_weight_reduced": None,
      "wealth_B_gt_threshold": None,
      "threshold": WEALTH_THRESHOLD,
    },
    "full_sample": {
      "baseline_16": _suite(full, "e2_16_pares"),
      "reduced_14": _suite(reduced, "e2_sin_dexe_zec"),
    },
    "halves": {},
  }

  for half in HALVES:
    results["halves"][half] = {
      "baseline_16": _suite(_slice(full, half), f"e2_16_{half}"),
      "reduced_14": _suite(_slice(reduced, half), f"e2_reducido_{half}"),
    }

  # Veredicto del criterio pre-fijado (muestra completa, universo reducido)
  red_b = results["full_sample"]["reduced_14"]["momentum_B"]["final_wealth"]
  ew_b = results["full_sample"]["reduced_14"]["equal_weight_B"]["final_wealth"]
  results["criterion"]["wealth_B_gt_equal_weight_reduced"] = bool(red_b > ew_b)
  results["criterion"]["wealth_B_gt_threshold"] = bool(red_b > WEALTH_THRESHOLD)
  results["criterion"]["momentum_B_wealth"] = red_b
  results["criterion"]["equal_weight_B_wealth"] = ew_b
  results["criterion"]["passes"] = bool(red_b > ew_b and red_b > WEALTH_THRESHOLD)

  # Contribución por par (universo completo, para la tabla de liquidez)
  contrib = _pair_contribution(full)
  qvol = _load_quote_volumes(E2_PAIRS)
  qvol_mean = qvol.mean()
  table = []
  for pair in contrib.sort_values(ascending=False).index:
    c = float(contrib[pair])
    v = float(qvol_mean.get(pair, float("nan")))
    table.append(
      {
        "pair": pair,
        "log_pnl_contribution": c,
        "mean_daily_quote_volume_usdt": v,
        "pnl_per_musd_volume": c / (v / 1e6) if v and v > 0 else None,
        "excluded_in_r0": pair in EXCLUDED,
      }
    )
  results["pair_contribution_table"] = table

  OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
  OUTPUT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")

  # Curvas
  import matplotlib

  matplotlib.use("Agg")
  import matplotlib.pyplot as plt

  fig, ax = plt.subplots(figsize=(11, 5))
  for label, prices, style in (
    ("top-3 E2 completo (B)", full, "-"),
    ("top-3 sin DEXE/ZEC (B)", reduced, "-"),
  ):
    rets, _ = portfolio_return(prices, _momentum_fn, FREQ, fee_per_rotation=FEE)
    ax.plot(rets.index, np.exp(rets.cumsum()), style, label=label, linewidth=1.3)
  rets_ew, _ = portfolio_return(reduced, weights_equal, FREQ, fee_per_rotation=FEE)
  ax.plot(rets_ew.index, np.exp(rets_ew.cumsum()), "--", label="equal-weight reducido (B)", linewidth=1.0)
  rets_btc, _ = portfolio_return(full, weights_btc_only, FREQ, fee_per_rotation=FEE)
  ax.plot(rets_btc.index, np.exp(rets_btc.cumsum()), ":", label="BTC B&H", linewidth=1.0)
  ax.axhline(WEALTH_THRESHOLD, color="gray", alpha=0.5, linewidth=0.8)
  ax.set_yscale("log")
  ax.set_ylabel("wealth (log)")
  ax.set_title("R0 — XSecMomentum ex-DEXE ex-ZEC (control #10)")
  ax.legend()
  ax.grid(True, alpha=0.3)
  fig.tight_layout()
  fig.savefig(OUTPUT_PNG, dpi=120)
  plt.close(fig)

  print(f"JSON: {OUTPUT_JSON}")
  print(f"PNG:  {OUTPUT_PNG}")
  print(
    f"Criterio: momentum_B={red_b:.2f}x vs EW_B={ew_b:.2f}x vs umbral {WEALTH_THRESHOLD}x "
    f"-> {'PASA' if results['criterion']['passes'] else 'FALLA'}"
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
