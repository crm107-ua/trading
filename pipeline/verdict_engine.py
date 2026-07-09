"""Motor de veredicto numérico Fase 4."""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.verdict import (
  DEFAULT_MAX_PARAM_DIVERGENCE,
  DEFAULT_MIN_TRADES_HYPEROPT,
  DEFAULT_OOS_SHARPE_RATIO_MIN,
  DEFAULT_WALK_FORWARD_EFFICIENCY_MIN,
  Verdict,
)

@dataclass
class SeedRunResult:
  seed: int
  is_metrics: dict
  oos_metrics: dict
  params_file: str
  param_divergence_vs_seed0: float | None = None


@dataclass
class VerdictInput:
  strategy: str
  baseline_oos_metrics: dict | None
  seed_results: list[SeedRunResult]
  walk_forward_efficiency: float | None
  max_param_divergence: float
  oos_sharpe_ratio_min: float = DEFAULT_OOS_SHARPE_RATIO_MIN
  wfe_min: float = DEFAULT_WALK_FORWARD_EFFICIENCY_MIN
  min_trades: int = DEFAULT_MIN_TRADES_HYPEROPT


@dataclass
class VerdictOutput:
  verdict: Verdict
  reasons: list[str]
  details: dict


def _primary_seed(result: SeedRunResult) -> SeedRunResult:
  return result


def compute_verdict(inp: VerdictInput) -> VerdictOutput:
  reasons: list[str] = []
  details: dict = {}

  if not inp.seed_results:
    return VerdictOutput(Verdict.DUDOSA, ["sin resultados de semillas"], details)

  primary = inp.seed_results[0]
  is_sharpe = float(primary.is_metrics.get("sharpe") or 0)
  oos_sharpe = float(primary.oos_metrics.get("sharpe") or 0)
  oos_profit = float(primary.oos_metrics.get("profit_total") or 0)
  is_trades = int(primary.is_metrics.get("trades") or 0)
  oos_trades = int(primary.oos_metrics.get("trades") or 0)

  details["is_sharpe"] = is_sharpe
  details["oos_sharpe"] = oos_sharpe
  details["oos_profit_total"] = oos_profit
  details["max_param_divergence"] = inp.max_param_divergence

  if is_trades < inp.min_trades:
    reasons.append(f"IS trades {is_trades} < mínimo {inp.min_trades}")

  if oos_profit < 0:
    reasons.append("OOS con PnL negativo")

  # Degradación IS→OOS solo si OOS no falla ya por rentabilidad. Con Sharpe
  # negativo el ratio 50% del IS es ambiguo (p. ej. -1.51 vs -1.90).
  sharpe_degradation_evaluated = oos_profit >= 0 and oos_sharpe >= 0
  details["sharpe_degradation_evaluated"] = sharpe_degradation_evaluated
  if sharpe_degradation_evaluated:
    if is_sharpe > 0 and oos_sharpe < is_sharpe * inp.oos_sharpe_ratio_min:
      reasons.append(
        f"Sharpe OOS ({oos_sharpe:.2f}) < {inp.oos_sharpe_ratio_min:.0%} del IS ({is_sharpe:.2f})"
      )
    elif is_sharpe <= 0 and oos_sharpe < is_sharpe:
      reasons.append("Sharpe OOS degradó respecto a IS (IS ya negativo)")

  if inp.max_param_divergence > DEFAULT_MAX_PARAM_DIVERGENCE:
    reasons.append(
      f"inestabilidad entre semillas (divergencia {inp.max_param_divergence:.2f})"
    )

  if inp.walk_forward_efficiency is not None:
    details["walk_forward_efficiency"] = inp.walk_forward_efficiency
    if inp.walk_forward_efficiency < inp.wfe_min:
      reasons.append(f"WFE {inp.walk_forward_efficiency:.2f} < {inp.wfe_min}")

  # Clasificación
  hard_fail = any(
    kw in r
    for r in reasons
    for kw in ("OOS con PnL negativo", "Sharpe OOS", "WFE")
  )
  if hard_fail:
    verdict = Verdict.SOBREAJUSTADA
  elif reasons:
    verdict = Verdict.DUDOSA
  else:
    verdict = Verdict.ROBUSTA

  details["oos_trades"] = oos_trades
  return VerdictOutput(verdict=verdict, reasons=reasons, details=details)
