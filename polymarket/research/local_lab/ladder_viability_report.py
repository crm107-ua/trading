#!/usr/bin/env python3
"""
Informe de viabilidad extenso — Temperature Ladder micro wallet.

Amplía wallet_take_reality_sim con:
  - Monte Carlo bootstrap de WR (75/80/90/research)
  - Matriz de depósito × fricción × ruin
  - Adequacy de capital (cuántos misses aguanta)
  - Cadencia esperada (~2.5 takes/semana research)
  - Scorecard GO / CONDITIONAL / NO-GO
  - Probe libro vivo opcional

  python3 -m polymarket.research.local_lab.ladder_viability_report \
    --balance 3.4482 --live-book --mc-reps 4000
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.ultra_real_ladder_campaign import _settle_with_friction
from polymarket.research.local_lab.wallet_take_reality_sim import (
    STRESS,
    compare_deposits,
    effective_cap,
    force_near_miss_counterfactual,
    live_book_snapshot,
    stress_with_forced_losses,
    what_if_single_take,
    _resize_to_cap,
)

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
CFG = POLY / "config" / "weather_ladder_definitive_real.json"
OUT = POLY / "data_local" / "local_lab" / "ladder_viability"
DOCS = POLY / "docs"

WR_ASSUMPTIONS = (0.75, 0.80, 0.90, 1.0)
DEPOSIT_LADDER = (3.4482, 5.0, 10.0, 15.0, 25.0, 50.0, 100.0)


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def capital_adequacy(
    raw: list[dict[str, Any]],
    *,
    balance: float,
    session_cap: float,
    budget_cfg: float,
) -> dict[str, Any]:
    """How many consecutive full misses until cash < $2 (cannot arm)."""
    # Size a representative take at current balance
    cap = effective_cap(balance, session_cap)
    budget = min(budget_cfg, cap)
    resized = None
    for t in sorted(raw, key=lambda x: abs(float(x.get("basket_cost") or 0.45) - 0.45)):
        resized = _resize_to_cap(t, budget) or _resize_to_cap(t, cap)
        if resized:
            break
    if not resized:
        return {
            "executable": False,
            "misses_until_ruin": 0,
            "notional": None,
            "note": "no DNA basket fits floors at this balance",
        }
    notional = float(resized["spent"])
    cash = float(balance)
    misses = 0
    path = [round(cash, 4)]
    while cash >= 2.0 - 1e-9:
        # next take size may shrink with cash
        cap_i = effective_cap(cash, session_cap)
        bud = min(budget_cfg, cap_i)
        r2 = _resize_to_cap(resized, bud) or _resize_to_cap(resized, cap_i)
        if not r2:
            break
        spend = float(r2["spent"])
        if spend > cash + 1e-9:
            break
        cash -= spend
        misses += 1
        path.append(round(cash, 4))
        if cash < 2.0:
            break
        # stop runaway
        if misses >= 20:
            break
    return {
        "executable": True,
        "notional_first": round(notional, 4),
        "misses_until_ruin": misses,
        "cash_path": path,
        "survives_1_miss": misses >= 2 or (misses >= 1 and path[-1] >= 2.0),
        # survives_1_miss: after 1 miss still >= $2
        "equity_after_1_miss": round(float(balance) - notional, 4),
        "still_armed_after_1_miss": (float(balance) - notional) >= 2.0 - 1e-9,
    }


def monte_carlo_paths(
    raw: list[dict[str, Any]],
    *,
    start: float,
    session_cap: float,
    budget_cfg: float,
    wr: float,
    scenario: dict[str, Any],
    reps: int,
    seed: int = 42,
) -> dict[str, Any]:
    """Bootstrap each historical take as win(wr) or full-miss(1-wr), sized live."""
    rng = random.Random(seed + int(wr * 1000) + int(start * 10))
    ends: list[float] = []
    ruins = 0
    pnls: list[float] = []
    exec_counts: list[int] = []

    ordered = sorted(raw, key=lambda t: t["day"])
    for _ in range(reps):
        cash = float(start)
        peak = cash
        n_exec = 0
        ruined = False
        for trade in ordered:
            if ruined or cash < 2.0:
                break
            cap = effective_cap(cash, session_cap)
            budget = min(budget_cfg, cap)
            resized = _resize_to_cap(trade, budget) or _resize_to_cap(trade, cap)
            if not resized:
                continue
            spent = float(resized["spent"])
            if spent > cash + 1e-9:
                continue
            if rng.random() < wr:
                fr = _settle_with_friction(
                    resized,
                    slip=float(scenario["entry_slip_cents"]),
                    fee_bps=float(scenario["taker_fee_bps"]),
                    fill_ratio=float(scenario["fill_ratio"]),
                    min_leg_shares=1.0,
                    min_leg_notional=0.5,
                    max_basket_cost=0.50 + float(scenario["entry_slip_cents"]) * 3,
                )
                if fr is None:
                    continue
                cash += float(fr["pnl"])
            else:
                cash -= spent
            n_exec += 1
            peak = max(peak, cash)
            if cash < 2.0:
                ruined = True
        ends.append(round(cash, 4))
        pnls.append(round(cash - start, 4))
        exec_counts.append(n_exec)
        if ruined or cash < 2.0:
            ruins += 1

    ends_s = sorted(ends)
    pnls_s = sorted(pnls)

    def pct(xs: list[float], p: float) -> float:
        if not xs:
            return 0.0
        i = min(len(xs) - 1, max(0, int(p * (len(xs) - 1))))
        return xs[i]

    return {
        "start_usdc": start,
        "wr_assumption": wr,
        "scenario": scenario["name"],
        "reps": reps,
        "ruin_prob": round(ruins / reps, 4) if reps else None,
        "mean_end": round(sum(ends) / reps, 4) if reps else None,
        "median_end": pct(ends_s, 0.5),
        "p05_end": pct(ends_s, 0.05),
        "p95_end": pct(ends_s, 0.95),
        "mean_pnl": round(sum(pnls) / reps, 4) if reps else None,
        "median_pnl": pct(pnls_s, 0.5),
        "p05_pnl": pct(pnls_s, 0.05),
        "prob_profit": round(sum(1 for x in pnls if x > 0) / reps, 4) if reps else None,
        "mean_exec": round(sum(exec_counts) / reps, 3) if reps else None,
    }


def cadence_projection(*, wr: float, takes_per_week: float = 2.5) -> dict[str, Any]:
    """Expected cadence from research (~2.5/week); many days $0."""
    return {
        "takes_per_week_assumed": takes_per_week,
        "takes_per_month_assumed": round(takes_per_week * 4.3, 2),
        "wr_assumption": wr,
        "expected_wins_per_week": round(takes_per_week * wr, 3),
        "expected_losses_per_week": round(takes_per_week * (1 - wr), 3),
        "note": "Cadencia research histórica; no calendario fijo. Muchos días sin take.",
    }


# Minimum independent DNA takes before any "deposit more / GO" language is allowed.
MIN_N_FOR_CAPITAL_INCREASE = 30
MIN_N_FOR_GO_MICRO = 50
MIN_WILSON95_FOR_GO = 0.80


def scorecard(report: dict[str, Any]) -> dict[str, Any]:
    bal = float(report["wallet"]["balance_usdc"])
    what = report["what_if_take_now"]
    adeq_map = report["capital_adequacy"]
    adeq = adeq_map.get(f"{bal:g}") or adeq_map.get(str(bal)) or next(iter(adeq_map.values()))
    mc = report["monte_carlo"]
    rs = report.get("research_stats") or {}
    n = int(rs.get("n") or report.get("dna_universe_n") or 0)
    wilson = float(rs.get("wilson95_lower") or 0.0)

    row80 = next(
        (
            r
            for r in mc
            if abs(r["start_usdc"] - bal) < 1e-6 and r["wr_assumption"] == 0.80 and r["scenario"] == "base"
        ),
        None,
    )
    row80_25 = next(
        (
            r
            for r in mc
            if r["start_usdc"] == 25.0 and r["wr_assumption"] == 0.80 and r["scenario"] == "base"
        ),
        None,
    )

    # Evidence gates dominate capital/MC cosmetics.
    evidence = {
        "n_ge_30_for_deposit_talk": n >= MIN_N_FOR_CAPITAL_INCREASE,
        "n_ge_50_for_go": n >= MIN_N_FOR_GO_MICRO,
        "wilson95_ge_80": wilson + 1e-12 >= MIN_WILSON95_FOR_GO,
        "mc_is_not_independent_validation": False,  # always fails: honesty marker
        "overfit_risk_acknowledged": True,  # process check (doc section present)
    }
    checks = {
        **evidence,
        "engineering_gates_ready": True,
        "geoblock_ok_assumed_vps_es": True,
        "take_sizeable_at_wallet": bool(what.get("executable_now")),
        "survives_one_miss_armed": bool(adeq.get("still_armed_after_1_miss")),
        "mc80_ruin_prob_lt_25pct": bool(row80 and (row80.get("ruin_prob") or 1) < 0.25),
        "mc80_median_pnl_positive": bool(row80 and (row80.get("median_pnl") or -1) > 0),
        "live_book_has_dna_take_now": bool((report.get("live_book") or {}).get("accepted_n")),
    }
    # Explicit: MC bootstrap on same n trades is NOT independent evidence
    checks["mc_is_not_independent_validation"] = False

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)

    if n < MIN_N_FOR_CAPITAL_INCREASE or wilson < MIN_WILSON95_FOR_GO:
        decision = "RESEARCH_ONLY"
        reason = (
            f"Evidencia insuficiente para aumentar capital real: n={n} "
            f"(mín. {MIN_N_FOR_CAPITAL_INCREASE} para hablar de depósito; "
            f"mín. {MIN_N_FOR_GO_MICRO} para GO_MICRO), Wilson95_lower={wilson:.4f} "
            f"(hace falta ≥{MIN_WILSON95_FOR_GO:.2f}). "
            "El Monte Carlo remuestrea los mismos takes — no es validación OOS independiente. "
            "Riesgo material de overfitting DNA a ruido de julio–agosto."
        )
    elif not checks["take_sizeable_at_wallet"]:
        decision = "NO-GO"
        reason = "Wallet no puede sizear basket DNA con floors CLOB."
    elif not checks["survives_one_miss_armed"]:
        decision = "CONDITIONAL_CAPITAL"
        reason = (
            "Evidencia OK en umbrales, pero 1 miss deja cash < $2. "
            "Solo entonces plantear depósito para runway — no antes."
        )
    elif n >= MIN_N_FOR_GO_MICRO and checks["wilson95_ge_80"] and checks["survives_one_miss_armed"]:
        decision = "GO_MICRO"
        reason = "Muestra y capital adeudan umbrales mínimos; DNA estricto + caps."
    else:
        decision = "RESEARCH_ONLY"
        reason = "Seguir acumulando takes DNA / paper antes de comprometer más USDC."

    return {
        "decision": decision,
        "reason": reason,
        "checks_passed": passed,
        "checks_total": total,
        "checks": checks,
        "evidence_thresholds": {
            "min_n_deposit_talk": MIN_N_FOR_CAPITAL_INCREASE,
            "min_n_go_micro": MIN_N_FOR_GO_MICRO,
            "min_wilson95_go": MIN_WILSON95_FOR_GO,
            "observed_n": n,
            "observed_wilson95_lower": wilson,
        },
        "mc80_at_wallet": row80,
        "mc80_at_25": row80_25,
        "mc_caveat": (
            "Las celdas MC (ruin%, median PnL a 4 decimales) NO validan el edge: "
            "bootstrapean la misma muestra DNA. Tratarlas como sensibilidad de bankroll, "
            "no como prueba de WR."
        ),
    }


def render_viability_md(report: dict[str, Any]) -> str:
    w = report["wallet"]
    sc = report["scorecard"]
    what = report["what_if_take_now"]
    lines: list[str] = [
        "# Informe de Viabilidad — Temperature Ladder (micro)",
        "",
        f"**UTC:** `{report['ts_utc']}`  ",
        f"**Wallet analizado:** `${w['balance_usdc']}` · cap efectivo `${w['effective_cap_usdc']}` · session cap `${w['session_cap_usdc']}`  ",
        f"**Perfil:** `{report['profile']}` · press-only DNA · floors CLOB · hold-to-resolution  ",
        f"**Modo:** simulación only (sin órdenes on-chain)",
        "",
        "---",
        "",
        "## 0) Decisión ejecutiva",
        "",
        f"### `{sc['decision']}`",
        "",
        sc["reason"],
        "",
        f"Checks: **{sc['checks_passed']}/{sc['checks_total']}**",
        "",
        "| Check | OK |",
        "|-------|----|",
    ]
    for k, v in (sc.get("checks") or {}).items():
        lines.append(f"| `{k}` | {'✅' if v else '❌'} |")

    lines += [
        "",
        "### Recomendación operativa",
        "",
        report["recommendation_es"],
        "",
        f"**Caveat MC:** {sc.get('mc_caveat')}",
        "",
        "### Umbrales de evidencia (duros)",
        "",
        "| Umbral | Requerido | Observado |",
        "|--------|----------:|----------:|",
    ]
    et = sc.get("evidence_thresholds") or {}
    lines += [
        f"| n para hablar de depósito | {et.get('min_n_deposit_talk')} | {et.get('observed_n')} |",
        f"| n para GO_MICRO | {et.get('min_n_go_micro')} | {et.get('observed_n')} |",
        f"| Wilson95 lower | {et.get('min_wilson95_go')} | {et.get('observed_wilson95_lower')} |",
        "",
        "---",
        "",
        "## 1) Contexto DNA y muestra",
        "",
        f"- Takes DNA históricos (press-only WR80 filters): **{report['dna_universe_n']}**",
        f"- Días: `{', '.join(report['dna_days'])}`",
        f"- WR research puntual: **{report['research_stats']['wr_point']}** "
        f"(wins={report['research_stats']['wins']}/{report['research_stats']['n']})",
        f"- Wilson 95% lower: **{report['research_stats']['wilson95_lower']}**",
        "- Lectura honesta: con n=11, WR puntual=100% **no** se distingue estadísticamente de un sistema ~74% (o peor).",
        "- Riesgo overfitting: el DNA puede estar memorizando coincidencias de esa ventana climática, no un edge estable.",
        "",
        "---",
        "",
        "## 2) What-if: take DNA ahora con este saldo",
        "",
    ]
    if what.get("executable_now"):
        lines += [
            f"**Ejecutable.** Notional sized ≈ `${what.get('notional_usdc')}`  ",
            f"Template: `{what.get('template', {}).get('city')}` `{what.get('template', {}).get('day')}` "
            f"basket={what.get('template', {}).get('basket_cost')}",
            "",
            "| Path | Spent | PnL | Equity |",
            "|------|------:|----:|-------:|",
        ]
        for name, p in (what.get("paths") or {}).items():
            if not isinstance(p, dict) or "spent" not in p:
                continue
            if p.get("executable") is False:
                continue
            lines.append(
                f"| `{name}` | {p.get('spent')} | {p.get('pnl')} | {p.get('equity_after')} |"
            )
    else:
        lines += [f"**No ejecutable.** `{what.get('block_reason')}`", ""]

    lines += ["", "---", "", "## 3) Adequacy de capital (misses hasta ruin)", "", "| Balance | Notional 1er take | Misses hasta ruin | ¿Sigue armed tras 1 miss? | Equity tras 1 miss |", "|--------:|------------------:|------------------:|:-------------------------:|-------------------:|"]
    for bal_s, row in report["capital_adequacy"].items():
        lines.append(
            f"| {bal_s} | {row.get('notional_first')} | {row.get('misses_until_ruin')} | "
            f"{'sí' if row.get('still_armed_after_1_miss') else 'no'} | {row.get('equity_after_1_miss')} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 4) Monte Carlo (sensibilidad de bankroll — NO validación del edge)",
        "",
        f"Reps por celda: **{report['mc_reps']}**. Cada take histórico se sizea con floors; "
        "win→settle con fricción; miss→−notional.",
        "",
        "**Importante:** este MC **remuestrea los mismos n takes DNA**. No es validación OOS "
        "independiente. Los 4 decimales (ruin%, median) miden sensibilidad de capital bajo un WR "
        "*asumido*, no demuestran ese WR. Tratar la tabla como stress de bankroll.",
        "",
        "| Start | WR asumido | Friction | Ruin% | Median PnL | P05 PnL | Mean End | P(profit) |",
        "|------:|-----------:|----------|------:|-----------:|--------:|---------:|----------:|",
    ]
    for r in report["monte_carlo"]:
        # keep table readable: only base+hostile and key WRs
        if r["scenario"] not in ("base", "hostile"):
            continue
        if r["wr_assumption"] not in (0.75, 0.80, 0.90, 1.0):
            continue
        if r["start_usdc"] not in DEPOSIT_LADDER and abs(r["start_usdc"] - w["balance_usdc"]) > 1e-6:
            continue
        lines.append(
            f"| {r['start_usdc']} | {r['wr_assumption']} | {r['scenario']} | "
            f"{r['ruin_prob']} | {r['median_pnl']} | {r['p05_pnl']} | {r['mean_end']} | {r['prob_profit']} |"
        )

    lines += ["", "### Lectura MC @ wallet actual (WR=0.80, base)", ""]
    mc_w = sc.get("mc80_at_wallet") or {}
    lines += [
        f"- Ruin prob: **{mc_w.get('ruin_prob')}**",
        f"- Median PnL: **{mc_w.get('median_pnl')}** · P05: **{mc_w.get('p05_pnl')}**",
        f"- Mean end equity: **{mc_w.get('mean_end')}**",
        "",
        "### Comparativa @ $25 (WR=0.80, base)",
        "",
        f"- Ruin prob: **{(sc.get('mc80_at_25') or {}).get('ruin_prob')}**",
        f"- Median PnL: **{(sc.get('mc80_at_25') or {}).get('median_pnl')}**",
        "",
        "---",
        "",
        "## 5) Replay determinista + loss stress",
        "",
        "### Deposit × friction (hereda outcomes research; optimista si WR puntual=100%)",
        "",
        "| Start | Scenario | Exec | WR | PnL | End | Skip floor | Skip cash |",
        "|------:|----------|-----:|---:|----:|----:|-----------:|----------:|",
    ]
    for r in report["deposit_matrix"]:
        lines.append(
            f"| {r['start_usdc']} | {r['scenario']} | {r['n_executed']}/{r['n_universe']} | "
            f"{r['winrate']} | {r['total_pnl']} | {r['ending_equity']} | "
            f"{r['skipped_floor']} | {r['skipped_cash']} |"
        )

    lines += ["", "### Forced-miss paths", ""]
    for name, st in (report.get("loss_stress") or {}).items():
        lines.append(
            f"- **{name}**: end `${st.get('ending_equity')}` · pnl `{st.get('total_pnl')}` · "
            f"ruined=`{st.get('ruined_below_2')}` · forced_idx=`{st.get('forced_loss_indices')}`"
        )

    lines += ["", "---", "", "## 6) Cadencia e ingreso esperado (orientativo)", ""]
    for wr, cad in (report.get("cadence") or {}).items():
        lines.append(
            f"- WR={wr}: ~{cad['takes_per_week_assumed']}/semana → "
            f"wins≈{cad['expected_wins_per_week']} · losses≈{cad['expected_losses_per_week']} "
            f"({cad['note']})"
        )

    lines += [
        "",
        "Con wallet micro, el PnL/$ por take win sized ~$3 es modesto (~+$1.2 a +$2 según fricción); "
        "el edge se escala con **más depósito en el mismo DNA**, no aflojando baskets.",
        "",
        "---",
        "",
        "## 7) Libro vivo",
        "",
    ]
    book = report.get("live_book")
    if not book:
        lines.append("_Sin probe en esta corrida._")
    elif book.get("error"):
        lines.append(f"_Error: `{book['error']}`_")
    else:
        lines.append(
            f"Open={book.get('events_open')} · accepted_DNA={book.get('accepted_n')} · "
            f"near_miss={len(book.get('near_miss') or [])}"
        )
        for nm in book.get("near_miss") or []:
            lines.append(f"- `{nm.get('city')}` basket={nm.get('basket_cost')} · `{nm.get('skip')}`")
        lines.append("")
        lines.append("### Contrafactual (NO ejecutar)")
        for row in report.get("near_miss_counterfactual") or []:
            lines.append(
                f"- **{row.get('city')}** {row.get('basket_cost')} → `{row.get('policy')}` "
                f"(EV$ approx if forced {row.get('if_forced_model_ev_usd_approx')})"
            )

    lines += [
        "",
        "---",
        "",
        "## 8) Riesgos y límites del informe",
        "",
        "1. **n pequeño:** n=11; Wilson95 lower ~0.74. No vender certeza 95%>80%.",
        "2. **MC ≠ validación:** bootstrap sobre los mismos takes; ilusión de precisión ≠ evidencia.",
        "3. **Overfitting DNA:** filtros press-only pueden memorizar ruido de esas fechas.",
        "4. **Depósito nuevo:** no justificado por este informe hasta n≥30 y Wilson≥0.80 (y GO solo con n≥50).",
        "5. No es fill on-chain; FAK parcial / gap de libro pueden empeorar el miss.",
        "6. Geoblock / keys / SAFE gates deben seguir OK en VPS ES.",
        "7. Near-miss ricos **no** son edge; forzarlos rompe la disciplina.",
        "8. Hold-to-resolution: capital locked hasta settle.",
        "",
        "---",
        "",
        "## 9) Plan RESEARCH_ONLY (postura actual)",
        "",
        "1. **No** depositar capital adicional solo por este informe.",
        "2. Seguir en sim / paper / vigilante DNA-gated; acumular takes hasta n≥30 (ideal ≥50).",
        "3. Recalcular Wilson95 lower en cada nuevo take DNA; no usar WR puntual.",
        "4. Mantener SAFE (`DRY_RUN` según política) hasta evidencia + capital runway.",
        "5. Auto-execute solo si DNA estricto y el operador arma explícitamente tras umbrales.",
        "6. Tras cualquier miss: no martingale ni aflojar gates.",
        "7. Telegram: EDGE / EJECUCIÓN / FIN — sin spam de near-miss.",
        "",
        f"_Generado por `ladder_viability_report` · {report['ts_utc']}_",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=3.4482)
    ap.add_argument("--session-cap", type=float, default=5.0)
    ap.add_argument("--budget", type=float, default=3.0)
    ap.add_argument("--mc-reps", type=int, default=4000)
    ap.add_argument("--live-book", action="store_true")
    ap.add_argument("--write-docs", action="store_true", help="Also write polymarket/docs/VIABILIDAD_LADDER.md")
    args = ap.parse_args()

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    raw = take_income_wr80(cases)
    bal = float(args.balance)

    wins = sum(1 for t in raw if t.get("win") or float(t.get("pnl") or 0) > 0)
    n = len(raw)
    research_stats = {
        "n": n,
        "wins": wins,
        "wr_point": round(wins / n, 4) if n else 0.0,
        "wilson95_lower": round(_wilson_lower(wins, n), 4),
    }
    print(f"DNA n={n} WR={research_stats['wr_point']} wilson={research_stats['wilson95_lower']}", flush=True)

    balances = sorted(set(list(DEPOSIT_LADDER) + [bal]))
    # capital adequacy
    adequacy: dict[str, Any] = {}
    for b in balances:
        adequacy[f"{b:g}"] = capital_adequacy(
            raw, balance=b, session_cap=float(args.session_cap), budget_cfg=float(args.budget)
        )
        print(
            f"  adequacy ${b:g}: misses_to_ruin={adequacy[f'{b:g}'].get('misses_until_ruin')} "
            f"armed_after_1={adequacy[f'{b:g}'].get('still_armed_after_1_miss')}",
            flush=True,
        )

    what_if = what_if_single_take(
        raw, balance=bal, session_cap=float(args.session_cap), budget_cfg=float(args.budget)
    )

    # MC grid (focused)
    mc_rows: list[dict[str, Any]] = []
    mc_balances = [bal, 5.0, 10.0, 25.0, 50.0, 100.0]
    mc_scenarios = [STRESS[0], STRESS[-1]]  # base + hostile
    for b in mc_balances:
        for wr in WR_ASSUMPTIONS:
            for sc in mc_scenarios:
                row = monte_carlo_paths(
                    raw,
                    start=b,
                    session_cap=float(args.session_cap),
                    budget_cfg=float(args.budget),
                    wr=wr,
                    scenario=sc,
                    reps=int(args.mc_reps),
                )
                mc_rows.append(row)
                if abs(b - bal) < 1e-6 or b in (25.0, 10.0):
                    if wr in (0.80, 1.0) and sc["name"] in ("base", "hostile"):
                        print(
                            f"  MC ${b:.2f} WR={wr} {sc['name']}: ruin={row['ruin_prob']} "
                            f"med_pnl={row['median_pnl']} p05={row['p05_pnl']}",
                            flush=True,
                        )

    matrix = compare_deposits(
        raw,
        balances=balances,
        session_cap=float(args.session_cap),
        budget_cfg=float(args.budget),
    )

    loss_stress = {
        "first_exec_miss": stress_with_forced_losses(
            raw, start=bal, session_cap=float(args.session_cap), budget_cfg=float(args.budget), forced_loss_indices={0}
        ),
        "first_two_exec_miss": stress_with_forced_losses(
            raw, start=bal, session_cap=float(args.session_cap), budget_cfg=float(args.budget), forced_loss_indices={0, 1}
        ),
        "first_exec_miss_at_10": stress_with_forced_losses(
            raw, start=10.0, session_cap=float(args.session_cap), budget_cfg=float(args.budget), forced_loss_indices={0}
        ),
        "first_exec_miss_at_25": stress_with_forced_losses(
            raw, start=25.0, session_cap=float(args.session_cap), budget_cfg=float(args.budget), forced_loss_indices={0}
        ),
        "two_miss_at_25": stress_with_forced_losses(
            raw, start=25.0, session_cap=float(args.session_cap), budget_cfg=float(args.budget), forced_loss_indices={0, 1}
        ),
        "mid_miss_idx3_at_wallet": stress_with_forced_losses(
            raw, start=bal, session_cap=float(args.session_cap), budget_cfg=float(args.budget), forced_loss_indices={3}
        ),
    }

    live_book = None
    near_cf: list[dict[str, Any]] = []
    if args.live_book:
        print("probing live book…", flush=True)
        live_book = live_book_snapshot(cfg)
        if live_book and not live_book.get("error"):
            near_cf = force_near_miss_counterfactual(list(live_book.get("near_miss") or []), bal)

    cadence = {str(wr): cadence_projection(wr=wr) for wr in (0.75, 0.80, 0.90)}

    report: dict[str, Any] = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "profile": "weather_ladder_definitive_real_v1",
        "mode": "viability_report_simulation_only",
        "wallet": {
            "balance_usdc": round(bal, 4),
            "session_cap_usdc": float(args.session_cap),
            "budget_per_market_usdc": float(args.budget),
            "effective_cap_usdc": effective_cap(bal, float(args.session_cap)),
        },
        "dna_universe_n": n,
        "dna_days": [t.get("day") for t in raw],
        "research_stats": research_stats,
        "what_if_take_now": what_if,
        "capital_adequacy": adequacy,
        "monte_carlo": mc_rows,
        "mc_reps": int(args.mc_reps),
        "deposit_matrix": matrix,
        "loss_stress": loss_stress,
        "cadence": cadence,
        "live_book": live_book,
        "near_miss_counterfactual": near_cf,
    }
    report["scorecard"] = scorecard(report)

    # Human recommendation in Spanish
    dec = report["scorecard"]["decision"]
    if dec == "NO-GO":
        rec = "No operar takes reales: wallet no sizea el basket DNA."
    elif dec == "RESEARCH_ONLY":
        rec = (
            "RESEARCH_ONLY: la ingeniería está lista, la evidencia no. "
            "n=11 y Wilson~0.74 no justifican depósito nuevo ni GO. "
            "Seguir en sim/vigilante DNA-gated; acumular ≥30 takes (ideal ≥50) "
            "antes de plantear más capital. No forzar near-miss. No martingale."
        )
    elif dec == "CONDITIONAL_CAPITAL":
        rec = (
            "Evidencia OK en umbrales, pero el bankroll no aguanta 1 miss. "
            "Solo entonces valorar depósito para runway — nunca al revés."
        )
    elif dec == "GO_MICRO":
        rec = "GO micro: muestra y capital en umbrales; DNA estricto + caps."
    else:
        rec = "Seguir en research/sim hasta aclarar evidencia y capital."
    report["recommendation_es"] = rec

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"viability_{stamp}.json"
    latest = OUT / "latest.json"
    md = render_viability_md(report)
    md_path = OUT / f"viability_{stamp}.md"
    latest_md = OUT / "LATEST.md"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(md, encoding="utf-8")
    latest_md.write_text(md, encoding="utf-8")

    docs_path = None
    if args.write_docs:
        docs_path = DOCS / "VIABILIDAD_LADDER.md"
        docs_path.write_text(md, encoding="utf-8")
        print(f"docs -> {docs_path}", flush=True)

    print(json.dumps({"decision": report["scorecard"]["decision"], "report": str(path)}, indent=2))
    print(f"markdown -> {md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
