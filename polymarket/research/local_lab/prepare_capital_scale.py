#!/usr/bin/env python3
"""
Prepare the durable Temperature Ladder for larger capital (SAFE, no posts).

Same DNA (press-only ≤0.50 / leg≤0.39 / UD). More income = more size + runway,
NOT looser filters. Builds capital-scale bankroll sims, miss-survival, and a
staged deposit playbook.

  python3 -m polymarket.research.local_lab.prepare_capital_scale
  python3 -m polymarket.research.local_lab.prepare_capital_scale --write-docs
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.high_income_project import project as hi_project
from polymarket.research.local_lab.long_term_robustness import evaluate_profile, make_profiles
from polymarket.research.local_lab.simulate_real_income import STRESS, simulate

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "capital_scale_prep"
DOCS = POLY / "docs"
VPS = POLY / "data_local" / "local_lab" / "vps_runs"
CORE = ("singapore", "shanghai", "hong-kong", "beijing")

# Extended capital ladder — DNA fixed; $/trade and session caps scale
CAPITAL_STAGES = (
    {
        "name": "micro",
        "deposit": 25.0,
        "budget": 5.0,
        "session_cap": 5.0,
        "max_session_loss": 5.0,
        "misses_to_survive": 1,
        "when": "Solo dry / proof of path",
    },
    {
        "name": "standard",
        "deposit": 50.0,
        "budget": 12.0,
        "session_cap": 15.0,
        "max_session_loss": 12.0,
        "misses_to_survive": 2,
        "when": "Tras 1ª ronda limpia en región permitida",
    },
    {
        "name": "high",
        "deposit": 100.0,
        "budget": 25.0,
        "session_cap": 50.0,
        "max_session_loss": 25.0,
        "misses_to_survive": 2,
        "when": "Escala objetivo: evidencia n≥50 + Wilson≥0.80",
    },
    {
        "name": "aggressive",
        "deposit": 200.0,
        "budget": 50.0,
        "session_cap": 100.0,
        "max_session_loss": 50.0,
        "misses_to_survive": 3,
        "when": "Tras ≥2 semanas high limpio",
    },
    {
        "name": "pro",
        "deposit": 500.0,
        "budget": 75.0,
        "session_cap": 150.0,
        "max_session_loss": 75.0,
        "misses_to_survive": 4,
        "when": "Desk estable; misma DNA; más buffer",
    },
    {
        "name": "desk",
        "deposit": 1000.0,
        "budget": 100.0,
        "session_cap": 200.0,
        "max_session_loss": 100.0,
        "misses_to_survive": 5,
        "when": "Escala desk; riesgo/trade ≤10% del bankroll",
    },
)

# Bankroll starts for compound sim (DNA takes chronological)
BANKROLL_STARTS = (25.0, 50.0, 100.0, 200.0, 500.0, 1000.0)


def _worst_miss_usdc(takes: list[dict[str, Any]], budget: float) -> float:
    """Approx full-basket loss at scaled budget (all legs miss)."""
    if not takes:
        return budget
    # spent scales ~linear; worst paper loss among takes, scaled
    worst = 0.0
    for t in takes:
        spent0 = float(t.get("spent") or 0) or 1.0
        pnl0 = float(t.get("pnl") or 0)
        # if win, theoretical miss ≈ -spent; if loss, use actual loss magnitude
        miss0 = -spent0 if pnl0 >= 0 else min(pnl0, -spent0)
        scaled = abs(miss0) * (budget / spent0)
        worst = max(worst, scaled)
    return round(max(worst, budget * 0.85), 2)


def miss_survival(balance: float, *, budget: float, takes: list[dict[str, Any]], n_misses: int) -> dict[str, Any]:
    miss = _worst_miss_usdc(takes, budget)
    after = balance - miss * n_misses
    # Still able to take at least one more trade after N misses
    still = after >= budget * 0.95
    return {
        "balance": balance,
        "budget": budget,
        "est_miss_usdc": miss,
        "n_misses": n_misses,
        "balance_after": round(after, 2),
        "still_can_trade": still,
        "runway_misses": int(balance // miss) if miss > 0 else 99,
    }


def bankroll_matrix(takes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    # Budget fracs for extended starts (compound, conservative)
    fracs = {
        25.0: 0.32,
        50.0: 0.18,
        100.0: 0.12,
        200.0: 0.10,
        500.0: 0.08,
        1000.0: 0.06,
    }
    # Monkey-patch via local simulate wrapper using budget override
    from polymarket.research.local_lab import simulate_real_income as sri

    old = dict(sri.BUDGET_FRACS)
    try:
        sri.BUDGET_FRACS = {**old, **fracs}
        for start in BANKROLL_STARTS:
            for sc in STRESS:
                if start not in sri.BUDGET_FRACS:
                    continue
                r = simulate(takes, start=float(start), scenario=sc)
                rows.append(
                    {
                        "start": r["start_usdc"],
                        "scenario": r["scenario"],
                        "n": r["n"],
                        "wr": r["winrate"],
                        "pnl": r["total_pnl"],
                        "end": r["ending_equity"],
                        "mult": r["return_mult"],
                        "dd": r["max_drawdown_frac"],
                        "pf": r["profit_factor"],
                        "income_positive": r["income_positive"],
                    }
                )
    finally:
        sri.BUDGET_FRACS = old
    return rows


def stage_plan(takes: list[dict[str, Any]], hi: dict[str, Any]) -> list[dict[str, Any]]:
    by_name = {s["name"]: s for s in (hi.get("scales") or [])}
    out = []
    for st in CAPITAL_STAGES:
        hi_s = by_name.get(st["name"])
        surv = miss_survival(
            st["deposit"],
            budget=st["budget"],
            takes=takes,
            n_misses=int(st["misses_to_survive"]),
        )
        # Risk per trade as fraction of deposit
        risk_frac = st["budget"] / st["deposit"]
        out.append(
            {
                **st,
                "risk_frac_of_deposit": round(risk_frac, 4),
                "risk_ok": risk_frac <= 0.30 + 1e-9,  # never >30% on a single take
                "miss_survival": surv,
                "week_clean": (hi_s or {}).get("expected_pnl_week"),
                "week_conservative": (hi_s or {}).get("conservative_pnl_week"),
                "month_clean": (hi_s or {}).get("expected_pnl_month"),
                "month_conservative": (hi_s or {}).get("conservative_pnl_month"),
                "ready_to_fund_when": [
                    "rearm_income_gate=READY_TO_REARM",
                    "n_dna>=50 and wilson>=0.80",
                    "región Polymarket permitida (no geoblock)",
                    f"balance>={st['deposit']}",
                    "POLY_LIVE_ARMED solo con ALLOW_REARM explícito",
                    "DNA press-only intacta",
                ],
            }
        )
    return out


def render_md(report: dict[str, Any]) -> str:
    lt = report.get("long_term") or {}
    lines = [
        "# Preparación con más capital (DNA intacta)",
        "",
        f"**UTC:** `{report['ts_utc']}`",
        f"**DNA takes:** n={report['dna_takes']['n']} WR={report['dna_takes']['wr']} "
        f"pnl_units={report['dna_takes']['pnl']}",
        f"**Long-term:** `{lt.get('verdict')}` profile=`{lt.get('profile')}`",
        "",
        "> Mejorar ingreso = **escalar capital** sobre el mismo edge durable. "
        "No aflojar basket/UD/select. **No depositar** hasta READY_TO_REARM.",
        "",
        "## Escala recomendada (objetivo)",
        "",
        "| Escala | Depósito | $/trade | Cap sesión | Misses buffer | Semana cons. | Mes cons. |",
        "|--------|----------|---------|------------|---------------|--------------|-----------|",
    ]
    for s in report["stages"]:
        lines.append(
            f"| **{s['name']}** | ${s['deposit']:g} | ~${s['budget']:g} | "
            f"${s['session_cap']:g} | {s['misses_to_survive']} "
            f"(runway={s['miss_survival']['runway_misses']}) | "
            f"${s.get('week_conservative')} | ${s.get('month_conservative')} |"
        )
    lines += [
        "",
        "## Bankroll compound (DNA + fricción)",
        "",
    ]
    # highlight key rows
    for start in (100.0, 200.0, 500.0, 1000.0):
        for sc in ("base", "hostile"):
            row = next(
                (r for r in report["bankroll"] if r["start"] == start and r["scenario"] == sc),
                None,
            )
            if row:
                lines.append(
                    f"- ${start:g} `{sc}`: n={row['n']} WR={row['wr']} "
                    f"pnl={row['pnl']} end={row['end']} mult={row['mult']} dd={row['dd']}"
                )
    rec = report.get("recommendation") or {}
    lines += [
        "",
        "## Recomendación de preparación",
        "",
        f"- **Target deposit (cuando gates verdes):** `${rec.get('target_deposit')}` "
        f"({rec.get('target_scale')})",
        f"- **Primera sesión:** budget `${rec.get('first_session_budget')}` · "
        f"cap `${rec.get('first_session_cap')}`",
        f"- **Por qué:** {rec.get('why_es')}",
        f"- **can_recommend_deposit_now:** `{rec.get('can_recommend_deposit_now')}`",
        "",
        "## Checklist prep (orden)",
        "",
    ]
    for i, step in enumerate(report.get("prep_steps") or [], 1):
        lines.append(f"{i}. {step}")
    lines += [
        "",
        "## Qué NO hacer",
        "",
        "- Aflojar DNA para “operar ya” con más capital",
        "- Depositar con n≪50 / Wilson≪0.80",
        "- Martingale tras un miss",
        "- Subir $/trade por encima del cap de la escala",
        "",
        "Ver: [`HIGH_INCOME.md`](HIGH_INCOME.md) · [`LONG_HORIZON_OPTIMAL.md`](LONG_HORIZON_OPTIMAL.md) · "
        "[`PREPARE_REAL_MONEY.md`](PREPARE_REAL_MONEY.md)",
        "",
    ]
    return "\n".join(lines)


def run(*, write_docs: bool = False) -> dict[str, Any]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    takes = take_income_wr80(cases)
    wins = sum(1 for t in takes if t.get("win"))
    n = len(takes)
    dna = {
        "n": n,
        "wins": wins,
        "wr": round(wins / n, 4) if n else 0.0,
        "pnl": round(sum(float(t["pnl"]) for t in takes), 2),
    }

    # Long-term confirm (income_wr80 only — fast)
    prof, post_b = make_profiles()["income_wr80"]
    uni = [c for c in cases if c["city"] in CORE]
    lt = evaluate_profile("income_wr80", prof, uni, post_max_basket=post_b)

    # Extended high-income projections (merge pro/desk into hi scales temporarily)
    from polymarket.research.local_lab import high_income_project as hip

    old_scales = hip.SCALES
    try:
        hip.SCALES = tuple(SCALES_FOR_HI())
        hi = hi_project(takes)
    finally:
        hip.SCALES = old_scales

    bank = bankroll_matrix(takes)
    stages = stage_plan(takes, hi)

    # Recommendation: prepare for HIGH now; fund only when evidence ready
    high = next(s for s in stages if s["name"] == "high")
    aggressive = next(s for s in stages if s["name"] == "aggressive")
    evidence_ok = n >= 50  # wilson checked elsewhere; here honest about n
    can_dep = False  # never true from this module alone
    recommendation = {
        "target_scale": "high",
        "target_deposit": high["deposit"],
        "stretch_scale": "aggressive",
        "stretch_deposit": aggressive["deposit"],
        "first_session_budget": 12.0,  # start below full high budget
        "first_session_cap": 25.0,
        "can_recommend_deposit_now": can_dep,
        "evidence_n_ok": evidence_ok,
        "why_es": (
            "Con más capital ($100→$200) el mismo DNA durable genera más $/semana. "
            f"Hoy n={n}<50 → preparar wallet/región/playbook, NO depositar aún. "
            f"$100 sobrevive ≥{high['miss_survival']['runway_misses']} misses @~$25/trade; "
            f"$200 runway≈{aggressive['miss_survival']['runway_misses']}."
        ),
    }

    prep_steps = [
        "Mantener WATCH_ONLY + forward snapshots hasta n≥50 / Wilson≥0.80.",
        "Re-certificar: `long_term_robustness --write-docs` + `simulate_real_income`.",
        f"Cuando READY_TO_REARM: depositar **${high['deposit']:g}** (escala high), no $3.",
        "Primera semana real: budget $12–$25, cap sesión $25–$50, max 1 ciudad.",
        "Si 2 semanas limpias: subir a aggressive ($200 / $50/trade) sin tocar DNA.",
        "Pro/desk ($500–$1000) solo con runway de misses y misma DNA.",
        "SAFE al terminar cada sesión; un miss → revisar, no doblar.",
    ]

    # Highlight bankroll gates for capital >=100
    big = [r for r in bank if r["start"] >= 100]
    all_pos = all(r["income_positive"] for r in big) if big else False

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "selection_objective": "scale_capital_keep_dna",
        "dna_takes": dna,
        "long_term": {
            "profile": lt["profile"],
            "verdict": lt["gate"]["verdict"],
            "passed": lt["gate"]["passed"],
            "overall": lt["overall"],
            "oos_wr": lt["walk_forward"].get("oos_wr"),
        },
        "high_income": {
            "trades_per_week": hi.get("trades_per_week"),
            "scales": hi.get("scales"),
            "verdict": hi.get("verdict"),
        },
        "stages": stages,
        "bankroll": bank,
        "bankroll_ge100_all_positive": all_pos,
        "recommendation": recommendation,
        "prep_steps": prep_steps,
        "disclaimer_es": (
            "Preparación + simulación. No posta. No autoriza depósito ni ALLOW_REARM."
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    VPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    (OUT / f"capital_prep_{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_md(report)
    (OUT / "LATEST.md").write_text(md, encoding="utf-8")
    (VPS / "CAPITAL_SCALE_PREP.md").write_text(md, encoding="utf-8")
    if write_docs:
        DOCS.mkdir(parents=True, exist_ok=True)
        (DOCS / "CAPITAL_SCALE_PREP.md").write_text(md, encoding="utf-8")
        # Refresh HIGH_INCOME table with extended scales
        _write_high_income_doc(hi, report)
        _write_prepare_real_money(report)
    return report


def SCALES_FOR_HI() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "name": s["name"],
            "budget": s["budget"],
            "deposit": s["deposit"],
            "session_cap": s["session_cap"],
        }
        for s in CAPITAL_STAGES
    )


def _write_high_income_doc(hi: dict[str, Any], report: dict[str, Any]) -> None:
    lines = [
        "# High income — mismo edge, más dólares",
        "",
        "**Principio:** ganar más = **escalar tamaño** en takes press-only, no aflojar filtros.",
        "**Prep capital:** [`CAPITAL_SCALE_PREP.md`](CAPITAL_SCALE_PREP.md)",
        "**Óptimo LT:** [`LONG_HORIZON_OPTIMAL.md`](LONG_HORIZON_OPTIMAL.md)",
        "",
        "| Escala | Depósito | $/trade | Semana limpia | Semana conservadora | Mes limpio | Mes conservador |",
        "|--------|----------|---------|---------------|---------------------|------------|-----------------|",
    ]
    for s in hi.get("scales") or []:
        mark = "**" if s["name"] in ("high", "aggressive") else ""
        lines.append(
            f"| {mark}{s['name']}{mark} | {mark}${s['deposit']:g}{mark} | "
            f"{mark}~${s['budget']:g}{mark} | "
            f"{mark}~${s['expected_pnl_week']}{mark} | ~${s['conservative_pnl_week']} | "
            f"~${s['expected_pnl_month']} | ~${s['conservative_pnl_month']} |"
        )
    rec = report["recommendation"]
    lines += [
        "",
        r"\*Conservador = haircut ×"
        f"{hi.get('conservative_mult', 0.57)} (fricción hostil + floors).",
        "",
        "## Target de preparación",
        "",
        f"- Depositar **${rec['target_deposit']:g}** (high) cuando `READY_TO_REARM` — no antes.",
        f"- Stretch **${rec['stretch_deposit']:g}** tras semanas limpias.",
        f"- Primera sesión real: budget `${rec['first_session_budget']}`, cap `${rec['first_session_cap']}`.",
        f"- can_recommend_deposit_now=`{rec['can_recommend_deposit_now']}` (evidencia aún corta).",
        "",
        "## Qué NO hacer",
        "",
        "- Meter tier `select` / quitar UD / basket >0.50",
        "- Forzar trades sin edge para “usar el capital”",
        "",
        "## Comandos",
        "",
        "```bash",
        "python3 -m polymarket.research.local_lab.prepare_capital_scale --write-docs",
        "python3 -m polymarket.research.local_lab.high_income_project",
        "python3 -m polymarket.research.local_lab.long_term_robustness --write-docs",
        "python3 -m polymarket.research.local_lab.real_env_ready --scale high",
        "```",
        "",
        "Config high: `polymarket/config/weather_ladder_high_income.json`",
        "",
    ]
    (DOCS / "HIGH_INCOME.md").write_text("\n".join(lines), encoding="utf-8")


def _write_prepare_real_money(report: dict[str, Any]) -> None:
    rec = report["recommendation"]
    md = "\n".join(
        [
            "# Prepare Real Money Battery",
            "",
            f"**UTC:** `{report['ts_utc']}`",
            "**Veredicto prep capital:** `CAPITAL_SCALE_PREP_READY` (sim/playbook) · "
            "**Depósito:** `NOT_YET` (evidencia)",
            "",
            "Ingeniería + DNA durable + proyecciones de capital listas. "
            "Mantener WATCH_ONLY. NO depositar ni armar hasta n≥50 / Wilson≥0.80 + READY_TO_REARM.",
            "",
            f"- Target deposit (cuando gates): **${rec['target_deposit']:g}** ({rec['target_scale']})",
            f"- Stretch: **${rec['stretch_deposit']:g}** ({rec['stretch_scale']})",
            f"- Long-term: `{report['long_term']['verdict']}`",
            f"- Bankroll ≥$100 all-positive (sim): `{report['bankroll_ge100_all_positive']}`",
            "",
            "Detalle: [`CAPITAL_SCALE_PREP.md`](CAPITAL_SCALE_PREP.md) · "
            "[`HIGH_INCOME.md`](HIGH_INCOME.md) · "
            "`python3 -m polymarket.research.local_lab.prepare_capital_scale --write-docs`",
            "",
        ]
    )
    (DOCS / "PREPARE_REAL_MONEY.md").write_text(md, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-docs", action="store_true")
    args = ap.parse_args()
    rep = run(write_docs=bool(args.write_docs))
    print(
        json.dumps(
            {
                "dna_takes": rep["dna_takes"],
                "long_term": rep["long_term"],
                "recommendation": rep["recommendation"],
                "stages": [
                    {
                        "name": s["name"],
                        "deposit": s["deposit"],
                        "budget": s["budget"],
                        "week_conservative": s.get("week_conservative"),
                        "runway_misses": s["miss_survival"]["runway_misses"],
                        "risk_ok": s["risk_ok"],
                    }
                    for s in rep["stages"]
                ],
                "bankroll_ge100_all_positive": rep["bankroll_ge100_all_positive"],
                "highlights": [
                    r
                    for r in rep["bankroll"]
                    if r["start"] in (100.0, 200.0, 500.0, 1000.0) and r["scenario"] in ("base", "hostile")
                ],
            },
            indent=2,
        )
    )
    ok = bool(rep["long_term"]["passed"] and rep["bankroll_ge100_all_positive"])
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
