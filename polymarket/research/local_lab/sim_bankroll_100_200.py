#!/usr/bin/env python3
"""
Simulación hipotética de bankroll alto ($100 / $200) — SIN dinero real.

Misma DNA press-only + floors CLOB + fricción. Session cap alto solo para
dejar sizear (comportamiento "si fuera real" con más capital).

  python3 -m polymarket.research.local_lab.sim_bankroll_100_200
  python3 -m polymarket.research.local_lab.sim_bankroll_100_200 --balances 100,200 --mc-reps 2000
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.ladder_viability_report import (
    capital_adequacy,
    monte_carlo_paths,
)
from polymarket.research.local_lab.wallet_take_reality_sim import (
    STRESS,
    compare_deposits,
    stress_with_forced_losses,
    what_if_single_take,
)

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "sim_bankroll_high"
DOCS = POLY / "docs"

# Hypothetical "real money" sizing (still DNA filters)
DEFAULT_SESSION_CAP = 50.0
DEFAULT_BUDGET = 25.0


def build_report(
    *,
    balances: list[float],
    session_cap: float,
    budget: float,
    mc_reps: int,
) -> dict[str, Any]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    raw = take_income_wr80(cases)

    adequacy: dict[str, Any] = {}
    what_ifs: dict[str, Any] = {}
    loss_stress: dict[str, Any] = {}
    for b in balances:
        key = f"{b:g}"
        adequacy[key] = capital_adequacy(
            raw, balance=b, session_cap=session_cap, budget_cfg=budget
        )
        what_ifs[key] = what_if_single_take(
            raw, balance=b, session_cap=session_cap, budget_cfg=budget
        )
        loss_stress[f"{key}_first_miss"] = stress_with_forced_losses(
            raw,
            start=b,
            session_cap=session_cap,
            budget_cfg=budget,
            forced_loss_indices={0},
        )
        loss_stress[f"{key}_two_miss"] = stress_with_forced_losses(
            raw,
            start=b,
            session_cap=session_cap,
            budget_cfg=budget,
            forced_loss_indices={0, 1},
        )

    matrix = compare_deposits(
        raw, balances=balances, session_cap=session_cap, budget_cfg=budget
    )

    mc_rows: list[dict[str, Any]] = []
    for b in balances:
        for wr in (0.75, 0.80, 0.90, 1.0):
            for sc in (STRESS[0], STRESS[-1]):
                mc_rows.append(
                    monte_carlo_paths(
                        raw,
                        start=b,
                        session_cap=session_cap,
                        budget_cfg=budget,
                        wr=wr,
                        scenario=sc,
                        reps=mc_reps,
                    )
                )

    return {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "simulation_only_no_orders",
        "note_es": (
            "Hipotético: mismo DNA, sizing con session_cap/budget altos para simular "
            "comportamiento con 100€/200€. No es permiso de GO ni rearme. "
            "n=11 sigue siendo evidencia débil — estas cifras son sensibilidad de bankroll."
        ),
        "dna_n": len(raw),
        "session_cap_usdc": session_cap,
        "budget_per_market_usdc": budget,
        "balances": balances,
        "capital_adequacy": adequacy,
        "what_if_take": what_ifs,
        "deposit_matrix": matrix,
        "loss_stress": loss_stress,
        "monte_carlo": mc_rows,
        "mc_reps": mc_reps,
    }


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# Sim bankroll $100 / $200 (hipotético, sin real)",
        "",
        f"**UTC:** `{report['ts_utc']}`",
        f"**DNA takes:** {report['dna_n']}",
        f"**Session cap sim:** `${report['session_cap_usdc']}` · budget/trade `${report['budget_per_market_usdc']}`",
        "",
        report["note_es"],
        "",
        "## Adequacy (misses hasta ruin)",
        "",
        "| Balance | Notional 1º | Misses hasta ruin | Armed tras 1 miss | Equity tras 1 miss |",
        "|--------:|------------:|------------------:|:-----------------:|-------------------:|",
    ]
    for k, row in (report.get("capital_adequacy") or {}).items():
        lines.append(
            f"| {k} | {row.get('notional_first')} | {row.get('misses_until_ruin')} | "
            f"{'sí' if row.get('still_armed_after_1_miss') else 'no'} | {row.get('equity_after_1_miss')} |"
        )

    lines += ["", "## What-if take DNA ahora", ""]
    for k, w in (report.get("what_if_take") or {}).items():
        lines.append(f"### ${k}")
        if not w.get("executable_now"):
            lines.append(f"- No ejecutable: `{w.get('block_reason')}`")
            continue
        lines.append(f"- Notional sized: `${w.get('notional_usdc')}`")
        lines.append("")
        lines.append("| Path | Spent | PnL | Equity |")
        lines.append("|------|------:|----:|-------:|")
        for name, p in (w.get("paths") or {}).items():
            if not isinstance(p, dict) or "spent" not in p:
                continue
            lines.append(
                f"| `{name}` | {p.get('spent')} | {p.get('pnl')} | {p.get('equity_after')} |"
            )
        lines.append("")

    lines += [
        "## Replay histórico DNA (optimista si WR puntual=100%)",
        "",
        "| Start | Scenario | Exec | WR | PnL | End |",
        "|------:|----------|-----:|---:|----:|----:|",
    ]
    for r in report.get("deposit_matrix") or []:
        if r["scenario"] not in ("base", "hostile"):
            continue
        lines.append(
            f"| {r['start_usdc']} | {r['scenario']} | {r['n_executed']}/{r['n_universe']} | "
            f"{r['winrate']} | {r['total_pnl']} | {r['ending_equity']} |"
        )

    lines += ["", "## Forced miss stress", ""]
    for name, st in (report.get("loss_stress") or {}).items():
        lines.append(
            f"- **{name}**: end `${st.get('ending_equity')}` · pnl `{st.get('total_pnl')}` · "
            f"ruined=`{st.get('ruined_below_2')}` · n_exec=`{st.get('n_executed')}`"
        )

    lines += [
        "",
        "## Monte Carlo (sensibilidad — NO validación OOS)",
        "",
        "| Start | WR | Friction | Ruin% | Median PnL | P05 PnL | Mean End |",
        "|------:|---:|----------|------:|-----------:|--------:|---------:|",
    ]
    for r in report.get("monte_carlo") or []:
        if r["scenario"] not in ("base", "hostile"):
            continue
        if r["wr_assumption"] not in (0.75, 0.80, 0.90):
            continue
        lines.append(
            f"| {r['start_usdc']} | {r['wr_assumption']} | {r['scenario']} | "
            f"{r['ruin_prob']} | {r['median_pnl']} | {r['p05_pnl']} | {r['mean_end']} |"
        )

    lines += [
        "",
        "## Lectura operativa",
        "",
        "- Con $100/$200 el path **sí aguanta varios misses** (a diferencia de $3.45).",
        "- El PnL hipotético escala con notional; el **edge DNA no está más demostrado**.",
        "- Rearme real sigue bloqueado por evidencia (n=11) — esto solo ilustra bankroll.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--balances", default="100,200")
    ap.add_argument("--session-cap", type=float, default=DEFAULT_SESSION_CAP)
    ap.add_argument("--budget", type=float, default=DEFAULT_BUDGET)
    ap.add_argument("--mc-reps", type=int, default=2000)
    ap.add_argument("--write-docs", action="store_true")
    args = ap.parse_args()

    balances = [float(x.strip()) for x in str(args.balances).split(",") if x.strip()]
    print(
        f"sim bankroll balances={balances} session_cap={args.session_cap} budget={args.budget}",
        flush=True,
    )
    report = build_report(
        balances=balances,
        session_cap=float(args.session_cap),
        budget=float(args.budget),
        mc_reps=int(args.mc_reps),
    )

    # compact stdout
    for k, a in report["capital_adequacy"].items():
        print(
            f"  adequacy ${k}: notional={a.get('notional_first')} "
            f"misses_ruin={a.get('misses_until_ruin')} armed_after_1={a.get('still_armed_after_1_miss')}",
            flush=True,
        )
    for r in report["monte_carlo"]:
        if r["wr_assumption"] == 0.80 and r["scenario"] in ("base", "hostile"):
            print(
                f"  MC ${r['start_usdc']} WR80 {r['scenario']}: ruin={r['ruin_prob']} "
                f"med={r['median_pnl']} p05={r['p05_pnl']}",
                flush=True,
            )

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"bankroll_{stamp}.json"
    md = render_md(report)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / f"bankroll_{stamp}.md").write_text(md, encoding="utf-8")
    (OUT / "LATEST.md").write_text(md, encoding="utf-8")
    if args.write_docs:
        (DOCS / "SIM_BANKROLL_100_200.md").write_text(md, encoding="utf-8")
        print(f"docs -> {DOCS / 'SIM_BANKROLL_100_200.md'}", flush=True)

    print(json.dumps({"report": str(path), "balances": balances}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
