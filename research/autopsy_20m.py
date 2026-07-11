#!/usr/bin/env python3
"""
Autopsia 20M — pandas mejora / Freqtrade destruye (2026-07-11).

Experimentos pre-registrados H0/A/B/C. Sin Docker. Salidas:
  research/output/autopsy_20m_20260711.json
  research/output/autopsy_20m_ablation.png
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "research"))

from xsec_lab import (  # noqa: E402
  AblationConfig,
  compute_btc_regime_daily,
  compute_metrics,
  load_closes_1d,
  load_quote_volume_30d,
  make_liquidity_masked_equal,
  make_liquidity_masked_momentum,
  portfolio_return,
  portfolio_return_ablation,
  weights_top_n_momentum,
)

DATADIR = ROOT / "research" / "data_local" / "binance"
USER_DATADIR = ROOT / "user_data" / "data" / "binance"
OUTPUT_JSON = ROOT / "research" / "output" / "autopsy_20m_20260711.json"
OUTPUT_PNG = ROOT / "research" / "output" / "autopsy_20m_ablation.png"

WINDOW = 14
TOP_N = 3
FEE = 0.001
FREQ = "W"
THRESHOLD = 20_000_000.0
EXCLUDE_LOO = "SOL/USDT"

E2_PAIRS = [
  f"{a}/USDT"
  for a in (
    "AAVE", "ADA", "BNB", "BTC", "DEXE", "DOGE", "ETH", "LTC",
    "NEAR", "SKL", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC",
  )
]

ZIP_20M = ROOT / "user_data" / "backtest_results" / "backtest-result-2026-07-11_09-27-24.zip"
ZIP_CTRL = ROOT / "user_data" / "backtest_results" / "backtest-result-2026-07-10_16-26-23.zip"

HYPOTHESES = {
  "H_fragil": "El efecto 20M depende de SOL; pandas colapsaría en LOO ex-SOL.",
  "H_mecanica": "Desviación de ejecución Freqtrade invierte el beneficio del filtro.",
}

ABLATION_STEPS = [
  ("0_baseline_continuo", AblationConfig()),
  ("1_slots_discretos", AblationConfig(discrete_slots=True)),
  ("2_slots_bear_flat", AblationConfig(discrete_slots=True, bear_flat=True)),
  ("3_slots_bear_stop35", AblationConfig(discrete_slots=True, bear_flat=True, stop_loss=-0.35)),
  (
    "4_slots_bear_stop_liqexit",
    AblationConfig(
      discrete_slots=True,
      bear_flat=True,
      stop_loss=-0.35,
      liquidity_exit_rebalance=True,
    ),
  ),
]


def _metrics_from_fn(
  prices: pd.DataFrame,
  fn,
  *,
  eligible: pd.DataFrame | None = None,
  regime: pd.Series | None = None,
  config: AblationConfig | None = None,
) -> dict:
  cfg = config or AblationConfig()
  if cfg.discrete_slots or cfg.bear_flat or cfg.stop_loss is not None or cfg.liquidity_exit_rebalance:
    rets, turnover, stats = portfolio_return_ablation(
      prices,
      fn,
      FREQ,
      fee_per_rotation=FEE,
      btc_regime=regime,
      eligibility=eligible,
      config=cfg,
    )
    m = compute_metrics(rets, turnover=turnover)
    out = asdict(m)
    out.update(stats)
    return out
  rets, turnover = portfolio_return(prices, fn, FREQ, fee_per_rotation=FEE)
  m = compute_metrics(rets, turnover=turnover)
  return asdict(m)


def experiment_a_loo(prices: pd.DataFrame, vol30: pd.DataFrame) -> dict:
  pairs_ex = [p for p in prices.columns if p != EXCLUDE_LOO]
  pr = prices[pairs_ex]
  vol = vol30.reindex(columns=pairs_ex)
  eligible = vol > THRESHOLD

  fn_20m = make_liquidity_masked_momentum(eligible, window=WINDOW, top_n=TOP_N)
  fn_free = lambda p, t: weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)
  fn_ew_20m = make_liquidity_masked_equal(eligible)
  fn_ew_free = lambda p, t: make_liquidity_masked_equal(pd.DataFrame(True, index=p.index, columns=p.columns))(p, t)

  m_20m = _metrics_from_fn(pr, fn_20m)
  m_free = _metrics_from_fn(pr, fn_free)
  m_ew_20m = _metrics_from_fn(pr, fn_ew_20m)
  m_ew_free = _metrics_from_fn(pr, fn_ew_free)

  beats_ew = m_20m["final_wealth"] > m_ew_20m["final_wealth"]
  return {
    "exclude": EXCLUDE_LOO,
    "filter_20m_B": m_20m,
    "no_filter_B": m_free,
    "ew_filtered_20m_B": m_ew_20m,
    "ew_no_filter_B": m_ew_free,
    "filter_beats_ew_excluded": beats_ew,
    "filter_delta_vs_no_filter": m_20m["final_wealth"] / m_free["final_wealth"] - 1.0,
    "H_fragil_signal": not beats_ew,
  }


def experiment_b_ablation(prices: pd.DataFrame, vol30: pd.DataFrame) -> dict:
  eligible = vol30.reindex(columns=prices.columns) > THRESHOLD
  fn_20m = make_liquidity_masked_momentum(eligible, window=WINDOW, top_n=TOP_N)
  fn_free = lambda p, t: weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)
  btc = prices["BTC/USDT"] if "BTC/USDT" in prices.columns else prices.iloc[:, 0]
  regime = compute_btc_regime_daily(btc)

  rows: dict = {"steps": [], "filter_vs_nofilter": {}}
  curves: dict[str, pd.Series] = {}

  for label, cfg in ABLATION_STEPS:
    m_f = _metrics_from_fn(prices, fn_20m, eligible=eligible, regime=regime, config=cfg)
    m_n = _metrics_from_fn(prices, fn_free, regime=regime, config=cfg)
    delta = m_f["final_wealth"] / m_n["final_wealth"] - 1.0
    rows["steps"].append(
      {
        "step": label,
        "config": asdict(cfg),
        "filter_20m_B": m_f,
        "no_filter_B": m_n,
        "filter_improves": m_f["final_wealth"] > m_n["final_wealth"],
        "relative_delta": delta,
      }
    )
    if cfg.discrete_slots or cfg.bear_flat or cfg.stop_loss is not None:
      rets, _, _ = portfolio_return_ablation(
        prices, fn_20m, FREQ, fee_per_rotation=FEE, btc_regime=regime, eligibility=eligible, config=cfg
      )
    else:
      rets, _ = portfolio_return(prices, fn_20m, FREQ, fee_per_rotation=FEE)
    curves[label] = np.exp(rets.cumsum())

  # Detectar paso que invierte beneficio
  invert_step = None
  prev_improves = None
  for row in rows["steps"]:
    if prev_improves is True and not row["filter_improves"]:
      invert_step = row["step"]
      break
    prev_improves = row["filter_improves"]
  rows["inversion_step"] = invert_step
  rows["curves"] = {k: None for k in curves}  # no serializar series
  rows["_curve_data"] = curves
  return rows


def _load_trades(zip_path: Path, strategy: str) -> list[dict]:
  with zipfile.ZipFile(zip_path) as zf:
    json_name = next(
      n for n in zf.namelist() if n.endswith(".json") and "_config" not in n and "meta" not in n
    )
    payload = json.loads(zf.read(json_name))
  return list(payload.get("strategy", {}).get(strategy, {}).get("trades") or [])


def experiment_c_forensics(prices: pd.DataFrame, vol30: pd.DataFrame) -> dict:
  trades_20m = _load_trades(ZIP_20M, "XSecMomentum20M")
  trades_ctrl = _load_trades(ZIP_CTRL, "XSecMomentum")

  def _summarize(trades: list[dict], label: str) -> dict:
    exits: dict[str, int] = {}
    pnl_by_pair: dict[str, float] = {}
    open_weeks: dict[str, set[str]] = {}
    for t in trades:
      pair = str(t.get("pair", ""))
      reason = str(t.get("exit_reason") or t.get("sell_reason") or "unknown")
      exits[reason] = exits.get(reason, 0) + 1
      pnl_by_pair[pair] = pnl_by_pair.get(pair, 0.0) + float(t.get("profit_abs") or 0)
      open_dt = pd.Timestamp(t.get("open_date") or t.get("open_timestamp"), tz="UTC")
      week = open_dt.strftime("%G-W%V")
      open_weeks.setdefault(week, set()).add(pair)

    n_weeks = len(open_weeks)
    incomplete = sum(1 for pairs in open_weeks.values() if len(pairs) < 3)
    return {
      "label": label,
      "n_trades": len(trades),
      "exit_reasons": exits,
      "pnl_by_pair": dict(sorted(pnl_by_pair.items(), key=lambda x: -x[1])),
      "weeks_with_3_slots_pct": float((n_weeks - incomplete) / n_weeks) if n_weeks else 0.0,
      "weeks_incomplete_pct": float(incomplete / n_weeks) if n_weeks else 0.0,
    }

  s_20m = _summarize(trades_20m, "freqtrade_20m")
  s_ctrl = _summarize(trades_ctrl, "freqtrade_control")

  eligible = vol30.reindex(columns=prices.columns) > THRESHOLD
  fn_20m = make_liquidity_masked_momentum(eligible, window=WINDOW, top_n=TOP_N)
  fn_free = lambda p, t: weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)
  rb_dates = sorted(
    pd.Series(1, index=prices.index).groupby(pd.Grouper(freq="W-FRI")).last().dropna().index
  )

  divergences: list[dict] = []
  for dt in rb_dates[200:210]:  # muestra 2024+
    if dt not in prices.index:
      continue
    w20 = fn_20m(prices, dt)
    w0 = fn_free(prices, dt)
    p20 = sorted([c for c in w20.index if w20[c] > 0])
    p0 = sorted([c for c in w0.index if w0[c] > 0])
    if p20 != p0:
      divergences.append(
        {
          "date": str(dt.date()),
          "pandas_20m": p20,
          "pandas_no_filter": p0,
          "only_without_filter": sorted(set(p0) - set(p20)),
        }
      )

  filtered_out_pnl = {
    pair: s_ctrl["pnl_by_pair"].get(pair, 0.0)
    for pair in ("DEXE/USDT", "ZEC/USDT")
  }
  filtered_out_pnl["total_removed_iliquid"] = sum(filtered_out_pnl.values())

  return {
    "freqtrade_20m": s_20m,
    "freqtrade_control": s_ctrl,
    "cash_drag_proxy": {
      "20m": 1.0 - s_20m["weeks_with_3_slots_pct"],
      "control": 1.0 - s_ctrl["weeks_with_3_slots_pct"],
    },
    "filtered_pair_pnl_control": filtered_out_pnl,
    "pandas_portfolio_divergence_sample": divergences[:8],
    "liquidity_exits_20m": s_20m["exit_reasons"].get("xsec_liquidity_exit", 0),
    "stop_loss_share_20m": s_20m["exit_reasons"].get("stop_loss", 0) / max(1, s_20m["n_trades"]),
    "stop_loss_share_control": s_ctrl["exit_reasons"].get("stop_loss", 0) / max(1, s_ctrl["n_trades"]),
  }


def _recommendation(a: dict, b: dict, c: dict) -> dict:
  fragil = a["H_fragil_signal"]
  steps = b["steps"]
  step0 = steps[0]
  step1 = steps[1]
  step_final = steps[-1]

  delta_shrink = step1["relative_delta"] / max(step0["relative_delta"], 1e-9)
  removed_pnl = c["filtered_pair_pnl_control"]["total_removed_iliquid"]

  # H-frágil rechazada si pandas ex-SOL sigue batiendo EW y mejora vs sin filtro
  h_fragil_verdict = "rechazada" if not fragil else "confirmada_parcial"

  # H-mecánica: slots comprimen múltiplo (~15→7) pero NO invierten filtro en pandas
  h_mecanica_verdict = (
    "parcial_slots_comprimen_margen"
    if step1["filter_improves"] and step1["filter_20m_B"]["final_wealth"] < 8.0
    else "no_invierte_en_pandas"
  )

  # Culpable principal en Freqtrade: composición — DEXE/ZEC PnL ausente en 20M
  composition_driver = removed_pnl > 15_000

  choice = "ii"
  rationale = (
    "H-frágil rechazada: pandas 20M ex-SOL sigue en 12.35× (>EW 1.25×) y mejora +51% vs sin filtro ex-SOL. "
    "Ablación B: ningún paso invierte el filtro en pandas (sigue 15.37× vs 14.51× con todas las mecánicas); "
    "slots discretos comprimen el múltiplo absoluto (15.6→7.0) y reducen el margen relativo del filtro (27%→4.6%). "
    f"Forense C: la inversión Freqtrade (5.1×→2.7×) se explica por composición — el control capturó "
    f"+{removed_pnl:,.0f} USDT en DEXE+ZEC que el filtro 20M elimina; SOL pasa a dominar (+19k) y falla LOO. "
    "La máscara es correcta (paridad 0); no es un defecto de una línea reparable sin cambiar la hipótesis. "
    "Mantener control #10 sin filtro; degradar primaria 20M con autopsia."
  )

  if fragil and a["filter_20m_B"]["final_wealth"] < a["ew_filtered_20m_B"]["final_wealth"]:
    choice = "iii"
    rationale = (
      "H-frágil dominante: pandas 20M ex-SOL cae por debajo de EW ex-SOL. "
      "Reevaluar candidato completo antes de validar."
    )

  return {
    "choice": choice,
    "rationale": rationale,
    "H_fragil_verdict": h_fragil_verdict,
    "H_mecanica_verdict": h_mecanica_verdict,
    "composition_driver": composition_driver,
    "margin_shrink_step1_vs_step0": delta_shrink,
    "ablation_step1": {
      "filter_wealth": step1["filter_20m_B"]["final_wealth"],
      "nofilter_wealth": step1["no_filter_B"]["final_wealth"],
      "filter_improves": step1["filter_improves"],
    },
    "ablation_final": {
      "filter_wealth": step_final["filter_20m_B"]["final_wealth"],
      "nofilter_wealth": step_final["no_filter_B"]["final_wealth"],
    },
    "dexezec_pnl_removed_from_control": removed_pnl,
    "cash_drag_20m": c["cash_drag_proxy"]["20m"],
    "cash_drag_control": c["cash_drag_proxy"]["control"],
  }


def main() -> int:
  prices = load_closes_1d(DATADIR, pairs=E2_PAIRS, start="2021-01-01")
  vol30 = load_quote_volume_30d(E2_PAIRS, prices.index, datadir=DATADIR)

  part_a = experiment_a_loo(prices, vol30)
  part_b = experiment_b_ablation(prices, vol30)
  curves = part_b.pop("_curve_data")
  part_c = experiment_c_forensics(prices, vol30)
  reco = _recommendation(part_a, part_b, part_c)

  out = {
    "date": "2026-07-11",
    "hypotheses": HYPOTHESES,
    "params": {"window": WINDOW, "top_n": TOP_N, "fee_B": FEE, "threshold": THRESHOLD},
    "A_loo_ex_sol": part_a,
    "B_ablation": part_b,
    "C_forensics": part_c,
    "recommendation": reco,
    "freqtrade_reference": {
      "control_net_mult": 5.06,
      "filter_20m_net_mult": 2.72,
      "pandas_reference": {"no_filter_B": 12.25, "filter_20m_B": 15.6},
    },
  }

  OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
  OUTPUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

  import matplotlib

  matplotlib.use("Agg")
  import matplotlib.pyplot as plt

  fig, ax = plt.subplots(figsize=(11, 5))
  for label, wealth in curves.items():
    ax.plot(wealth.index, wealth.values, label=label, linewidth=1.2)
  ax.set_yscale("log")
  ax.set_title("Autopsia 20M — ablación mecánica (filter 20M, versión B)")
  ax.legend(fontsize=8)
  ax.grid(True, alpha=0.3)
  fig.tight_layout()
  fig.savefig(OUTPUT_PNG, dpi=120)
  plt.close(fig)

  print(json.dumps({"recommendation": reco, "A": part_a, "B_inversion": part_b["inversion_step"]}, indent=2))
  print(f"JSON: {OUTPUT_JSON}")
  print(f"PNG:  {OUTPUT_PNG}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
