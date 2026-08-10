#!/usr/bin/env python3
"""
Simulate real cases → improve paper strategy → report gains (SAFE, no posts).

Uses weather_optimize/cases.json (resolved real markets). Compares:
  - LIVE_DNA: press-only take_income_wr80 (same gates as production)
  - PAPER grid: basket/leg/UD/select/bias variants (research only)
  - Walk-forward OOS: champion must also print gains on the later half of days

For each variant: chronological bankroll sim at $25/$50/$100 with friction stress.
Never modifies weather_ladder_definitive_real.json.

  python3 -m polymarket.research.local_lab.sim_strategy_improve
  python3 -m polymarket.research.local_lab.sim_strategy_improve --write-docs
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.optimize_weather_ladder import TrialFilters, _eval_case
from polymarket.research.local_lab.simulate_real_income import STARTS, STRESS, gate_ok, simulate
from polymarket.research.local_lab.validate_two_tier import (
    BJ_PRESS,
    BJ_SELECT,
    CORE_PRESS,
    CORE_SELECT,
)

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "sim_strategy_improve"
DOCS = POLY / "docs"
VPS = POLY / "data_local" / "local_lab" / "vps_runs"

CORE = ("singapore", "shanghai", "hong-kong")


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def _score_takes(takes: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(1 for t in takes if t.get("win") or float(t.get("pnl") or 0) > 0)
    n = len(takes)
    pnl = sum(float(t.get("pnl") or 0) for t in takes)
    return {
        "n": n,
        "wins": wins,
        "wr_point": round(wins / n, 4) if n else 0.0,
        "wilson95_lower": round(_wilson_lower(wins, n), 4),
        "pnl_sum_paper_units": round(pnl, 2),
    }


def _day_split(cases: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    days = sorted({c.get("day") for c in cases if c.get("day")})
    if not days:
        return set(), set()
    cut = max(1, len(days) // 2)
    return set(days[:cut]), set(days[cut:])


def take_filters(
    cases: list[dict[str, Any]],
    *,
    core_filt: TrialFilters,
    bj_filt: TrialFilters,
    allow_select: bool = False,
    select_core: TrialFilters | None = None,
    select_bj: TrialFilters | None = None,
) -> list[dict[str, Any]]:
    taken: list[dict[str, Any]] = []
    for case in sorted(cases, key=lambda c: c.get("day") or ""):
        city = case.get("city")
        if city in CORE:
            flist = [("press", core_filt)]
            if allow_select and select_core is not None:
                flist.append(("select", select_core))
        elif city == "beijing":
            flist = [("press", bj_filt)]
            if allow_select and select_bj is not None:
                flist.append(("select", select_bj))
        else:
            continue
        for name, filt in flist:
            r = _eval_case(case, filt)
            if r and r.get("taken"):
                taken.append({**r, "variant_tier": name})
                break
    return taken


def take_variant(cases: list[dict[str, Any]], *, mode: str) -> list[dict[str, Any]]:
    if mode == "live_dna_press":
        return take_income_wr80(cases)

    if mode == "paper_press_select":
        return take_filters(
            cases,
            core_filt=CORE_PRESS,
            bj_filt=BJ_PRESS,
            allow_select=True,
            select_core=CORE_SELECT,
            select_bj=BJ_SELECT,
        )
    if mode == "paper_press_only_strict":
        return take_filters(cases, core_filt=CORE_PRESS, bj_filt=TrialFilters(0.50, 0.39, 0.35, 0.01, True, 3, 12.0, 1.0))
    if mode == "paper_basket_52_ud":
        return take_filters(
            cases,
            core_filt=TrialFilters(0.52, 0.39, 0.35, 0.01, True, 3, 12.0, 0.5),
            bj_filt=TrialFilters(0.52, 0.39, 0.35, 0.01, True, 3, 12.0, 1.0),
        )
    if mode == "paper_basket_55_ud":
        return take_filters(
            cases,
            core_filt=TrialFilters(0.55, 0.39, 0.35, 0.01, True, 3, 12.0, 0.5),
            bj_filt=TrialFilters(0.55, 0.39, 0.35, 0.01, True, 3, 12.0, 1.0),
        )
    if mode == "paper_no_ud_press":
        return take_filters(
            cases,
            core_filt=TrialFilters(0.50, 0.39, 0.35, 0.01, False, 3, 12.0, 0.5),
            bj_filt=TrialFilters(0.50, 0.39, 0.35, 0.01, False, 3, 12.0, 1.0),
        )
    if mode.startswith("grid:"):
        # grid:mbasket_mleg_ud_select_biascore_biasbj
        # e.g. grid:0.50_0.39_1_0_0.5_1.0
        _, payload = mode.split(":", 1)
        parts = payload.split("_")
        mb, ml, ud, sel, bc, bb = (
            float(parts[0]),
            float(parts[1]),
            parts[2] == "1",
            parts[3] == "1",
            float(parts[4]),
            float(parts[5]),
        )
        core = TrialFilters(mb, ml, 0.35, 0.01, ud, 3, 12.0, bc)
        bj = TrialFilters(mb, ml, 0.35, 0.01, ud, 3, 12.0, bb)
        sel_core = TrialFilters(mb, ml, 0.35, 0.01, False, 3, 12.0, bc) if sel else None
        sel_bj = TrialFilters(mb, ml, 0.35, 0.01, False, 3, 12.0, bb) if sel else None
        return take_filters(
            cases,
            core_filt=core,
            bj_filt=bj,
            allow_select=sel,
            select_core=sel_core,
            select_bj=sel_bj,
        )
    raise ValueError(mode)


def paper_grid_modes() -> list[str]:
    """Dense paper search — still research-only; never promoted to live DNA."""
    modes = [
        "paper_press_only_strict",
        "paper_press_select",
        "paper_basket_52_ud",
        "paper_basket_55_ud",
        "paper_no_ud_press",
    ]
    for mb in (0.48, 0.50, 0.52, 0.55, 0.58):
        for ml in (0.36, 0.39, 0.42):
            for ud in (0, 1):
                for sel in (0, 1):
                    for bc, bb in ((0.5, 1.0), (0.0, 0.0), (1.0, 1.0)):
                        modes.append(f"grid:{mb:.2f}_{ml:.2f}_{ud}_{sel}_{bc}_{bb}")
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for m in modes:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def bankroll_matrix(takes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for start in STARTS:
        for sc in STRESS:
            rows.append(simulate(takes, start=float(start), scenario=sc))
    g = gate_ok(rows)
    compact = []
    for r in rows:
        compact.append(
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
            }
        )
    base100 = next((c for c in compact if c["start"] == 100 and c["scenario"] == "base"), None)
    hostile100 = next((c for c in compact if c["start"] == 100 and c["scenario"] == "hostile"), None)
    base25 = next((c for c in compact if c["start"] == 25 and c["scenario"] == "base"), None)
    return {
        "gate": g,
        "rows": compact,
        "highlight": {"base25": base25, "base100": base100, "hostile100": hostile100},
    }


def _clean_takes(takes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in takes if t.get("legs") and t.get("day") is not None]


def evaluate_mode(cases: list[dict[str, Any]], mode: str, *, is_days: set[str] | None = None) -> dict[str, Any]:
    subset = cases if is_days is None else [c for c in cases if c.get("day") in is_days]
    clean = _clean_takes(take_variant(subset, mode=mode))
    bank = (
        bankroll_matrix(clean)
        if clean
        else {"gate": {"passed": False, "verdict": "NO_TAKES"}, "rows": [], "highlight": {}}
    )
    return {
        "mode": mode,
        "live_safe": mode == "live_dna_press",
        "takes": _score_takes(clean),
        "bankroll": bank,
    }


def rank_key(rep: dict[str, Any]) -> tuple:
    """Prefer: income gate, OOS hostile pnl, full hostile, full base, n, wilson."""
    g = rep["bankroll"]["gate"]
    h = rep["bankroll"]["highlight"]
    oos = (rep.get("oos") or {}).get("highlight") or {}
    return (
        1 if g.get("passed") else 0,
        1 if (rep.get("oos") or {}).get("gate_passed") else 0,
        float((oos.get("hostile100") or {}).get("pnl") or -1e9),
        float((oos.get("base100") or {}).get("pnl") or -1e9),
        float((h.get("hostile100") or {}).get("pnl") or -1e9),
        float((h.get("base100") or {}).get("pnl") or -1e9),
        int(rep["takes"]["n"]),
        float(rep["takes"]["wilson95_lower"]),
    )


def render_md(report: dict[str, Any]) -> str:
    champ = report["champion_paper"]
    live = report["live_dna"]
    lines = [
        "# Simulación con cases reales — mejora de estrategia (PAPER)",
        "",
        f"**UTC:** `{report['ts_utc']}`",
        f"**Cases:** {report['n_cases']}",
        f"**Grid paper evaluado:** {report.get('n_paper_modes')}",
        f"**IS days / OOS days:** {report.get('n_is_days')} / {report.get('n_oos_days')}",
        "",
        "> Simulación + fricción sobre cases reales. **No** es permiso de depósito ni cambio de DNA live.",
        "",
        "## LIVE DNA (press-only, producción)",
        f"- takes n={live['takes']['n']} WR={live['takes']['wr_point']} Wilson={live['takes']['wilson95_lower']}",
        f"- pnl paper units={live['takes']['pnl_sum_paper_units']}",
        f"- bankroll $25 base: {live['bankroll']['highlight'].get('base25')}",
        f"- bankroll $100 base: {live['bankroll']['highlight'].get('base100')}",
        f"- bankroll $100 hostile: {live['bankroll']['highlight'].get('hostile100')}",
        f"- income_gate_passed={live['bankroll']['gate'].get('passed')} verdict={live['bankroll']['gate'].get('verdict')}",
        "",
        "## Champion operacional (= LIVE DNA)",
        f"- mode=`{champ['mode']}`",
        f"- takes n={champ['takes']['n']} WR={champ['takes']['wr_point']} Wilson={champ['takes']['wilson95_lower']}",
        f"- pnl paper units={champ['takes']['pnl_sum_paper_units']}",
        f"- $25 base: {champ['bankroll']['highlight'].get('base25')}",
        f"- $100 base: {champ['bankroll']['highlight'].get('base100')}",
        f"- $100 hostile: {champ['bankroll']['highlight'].get('hostile100')}",
        f"- income_gate_passed={champ['bankroll']['gate'].get('passed')} verdict={champ['bankroll']['gate'].get('verdict')}",
        f"- OOS $100 base: {((champ.get('oos') or {}).get('highlight') or {}).get('base100')}",
        f"- Robust eligible paper modes: {report.get('n_robust_eligible')}",
        f"- Near-live eligible: {report.get('n_near_live_eligible')}",
        "",
    ]
    rc = report.get("research_champion")
    if rc and rc.get("mode") != champ.get("mode"):
        lines += [
            "## Research PAPER champion (NO live)",
            f"- mode=`{rc['mode']}` takes={rc['takes']}",
            f"- $100 base: {(rc.get('bankroll') or {}).get('highlight', {}).get('base100')}",
            f"- OOS base100: {((rc.get('oos') or {}).get('highlight') or {}).get('base100')}",
            "",
        ]
    nl = report.get("near_live_champion")
    if nl:
        lines += [
            "## Near-live PAPER (≤0.50 / UD / leg≤0.39, NO promote)",
            f"- mode=`{nl['mode']}` takes={nl['takes']}",
            f"- $100 base: {(nl.get('bankroll') or {}).get('highlight', {}).get('base100')}",
            "",
        ]
    agr = report.get("aggressive_paper")
    if agr:
        lines += [
            "## Aggressive PAPER max-PnL (NO live)",
            f"- mode=`{agr['mode']}` takes={agr['takes']}",
            f"- $100 base: {(agr.get('highlight') or {}).get('base100')}",
            f"- OOS: {((agr.get('oos') or {}).get('highlight') or {}).get('base100')}",
            "",
        ]
    lines += [
        "## Top 8 variantes (por ranking OOS+gate)",
    ]
    for v in report["variants"][:8]:
        h = v["bankroll"]["highlight"]
        oos_h = ((v.get("oos") or {}).get("highlight") or {})
        lines.append(
            f"- `{v['mode']}` n={v['takes']['n']} WR={v['takes']['wr_point']} "
            f"base100_pnl={(h.get('base100') or {}).get('pnl')} "
            f"hostile100_pnl={(h.get('hostile100') or {}).get('pnl')} "
            f"oos_base100={(oos_h.get('base100') or {}).get('pnl')} "
            f"gate={v['bankroll']['gate'].get('passed')}"
        )
    lines += [
        "",
        "## Conclusión",
        "",
        report.get("conclusion_es") or "",
        "",
        "## Live posture",
        "",
        "- DNA live sigue press-only ≤0.50 / leg≤0.39 / UD.",
        "- Ganancias de esta sim **no** autorizan depósito hasta READY_TO_REARM.",
        "",
    ]
    return "\n".join(lines)


def run(*, write_docs: bool = False, full_grid: bool = True) -> dict[str, Any]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    is_days, oos_days = _day_split(cases)

    modes = ["live_dna_press"] + (paper_grid_modes() if full_grid else [
        "paper_press_only_strict",
        "paper_press_select",
        "paper_basket_52_ud",
        "paper_basket_55_ud",
        "paper_no_ud_press",
    ])

    variants: list[dict[str, Any]] = []
    for mode in modes:
        full = evaluate_mode(cases, mode)
        oos = evaluate_mode(cases, mode, is_days=oos_days)
        full["oos"] = {
            "takes": oos["takes"],
            "highlight": oos["bankroll"]["highlight"],
            "gate_passed": bool(oos["bankroll"]["gate"].get("passed")),
            "gate_verdict": oos["bankroll"]["gate"].get("verdict"),
        }
        variants.append(full)

    live = next(v for v in variants if v["mode"] == "live_dna_press")
    paper = [v for v in variants if v["mode"] != "live_dna_press"]

    def _pnl(block: dict[str, Any] | None, key: str) -> float:
        return float((((block or {}).get(key) or {}).get("pnl")) or -1e9)

    def _wr(block: dict[str, Any] | None, key: str) -> float:
        return float((((block or {}).get(key) or {}).get("wr")) or 0.0)

    # Robust champion: OOS profit + settled WR≥80% + income gate + n≥5
    eligible = []
    for v in paper:
        h = v["bankroll"]["highlight"]
        oos_h = (v.get("oos") or {}).get("highlight") or {}
        if int(v["takes"]["n"]) < 5:
            continue
        if _pnl(oos_h, "base100") <= 0 or _pnl(oos_h, "hostile100") < 0:
            continue
        if _wr(h, "base100") < 0.80 or _wr(oos_h, "base100") < 0.80:
            continue
        if not v["bankroll"]["gate"].get("passed"):
            continue
        eligible.append(v)

    # Aggressive max-pnl paper (reported separately; never live)
    aggressive = sorted(
        [
            v
            for v in paper
            if int(v["takes"]["n"]) >= 5 and _pnl(v["bankroll"]["highlight"], "base100") > 0
        ],
        key=lambda v: (
            _pnl(v["bankroll"]["highlight"], "base100"),
            _pnl((v.get("oos") or {}).get("highlight"), "base100"),
        ),
        reverse=True,
    )
    agr = aggressive[0] if aggressive else None

    # Near-live paper: only DNA-compatible gates (basket≤0.50, UD on, leg≤0.39)
    near_live = []
    for v in paper:
        mode = v["mode"]
        if mode.startswith("grid:"):
            parts = mode.split(":", 1)[1].split("_")
            mb, ml, ud = float(parts[0]), float(parts[1]), parts[2]
            if mb > 0.50 + 1e-9 or ml > 0.39 + 1e-9 or ud != "1":
                continue
        elif mode not in ("paper_press_only_strict",):
            continue
        if v not in eligible:
            continue
        near_live.append(v)
    near_sorted = sorted(near_live, key=rank_key, reverse=True)
    near = near_sorted[0] if near_sorted else None

    pool = eligible or []
    paper_sorted = sorted(pool, key=rank_key, reverse=True)
    research_champ = paper_sorted[0] if paper_sorted else live
    # Operational champion never leaves LIVE DNA in this module
    champ = live
    if near and _pnl(near["bankroll"]["highlight"], "hostile100") > _pnl(
        live["bankroll"]["highlight"], "hostile100"
    ):
        # Still do not promote; only annotate near-live edge
        pass

    def _fmt_pnl(block: dict[str, Any] | None) -> str:
        if not isinstance(block, dict):
            return "n/a"
        return f"pnl={block.get('pnl')} wr={block.get('wr')} n={block.get('n')}"

    live_profit = (live["bankroll"]["highlight"].get("base100") or {}).get("pnl")
    research_profit = (research_champ["bankroll"]["highlight"].get("base100") or {}).get("pnl")
    live_oos = (live.get("oos") or {}).get("highlight") or {}
    research_oos = (research_champ.get("oos") or {}).get("highlight") or {}
    near_profit = (
        (near["bankroll"]["highlight"].get("base100") or {}).get("pnl") if near else None
    )
    conclusion = (
        f"LIVE DNA ya genera ganancias en sim ($100 base pnl={live_profit}; "
        f"OOS base100 {_fmt_pnl(live_oos.get('base100'))}). "
        f"Champion operacional=`live_dna_press` (DNA intacta). "
        f"Mejor paper research=`{research_champ['mode']}` "
        f"($100 base pnl={research_profit}, OOS {_fmt_pnl(research_oos.get('base100'))}). "
    )
    if near:
        conclusion += (
            f"Mejor near-live (≤0.50/UD/leg≤0.39)=`{near['mode']}` "
            f"(base100 pnl={near_profit}). "
        )
    if agr and agr["mode"] != research_champ["mode"]:
        ah = agr["bankroll"]["highlight"].get("base100") or {}
        conclusion += (
            f"Máximo PnL paper agresivo=`{agr['mode']}` "
            f"(base100 pnl={ah.get('pnl')} wr={ah.get('wr')} n_takes={agr['takes']['n']}). "
        )
    conclusion += (
        "Ninguna variante paper se promueve a live hasta n≥50 + Wilson≥0.80 + READY_TO_REARM. "
        "Seguir capturando forward DNA."
    )

    ranked = sorted(variants, key=rank_key, reverse=True)
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(cases),
        "n_paper_modes": len(modes) - 1,
        "n_is_days": len(is_days),
        "n_oos_days": len(oos_days),
        "is_day_range": [min(is_days), max(is_days)] if is_days else [],
        "oos_day_range": [min(oos_days), max(oos_days)] if oos_days else [],
        "live_dna": live,
        "champion_paper": champ,
        "research_champion": research_champ,
        "near_live_champion": near,
        "aggressive_paper": (
            {
                "mode": agr["mode"],
                "takes": agr["takes"],
                "highlight": agr["bankroll"]["highlight"],
                "oos": agr.get("oos"),
                "gate": agr["bankroll"]["gate"].get("verdict"),
            }
            if agr
            else None
        ),
        "n_robust_eligible": len(eligible),
        "n_near_live_eligible": len(near_live),
        "variants": ranked,
        "top8": [
            {
                "mode": v["mode"],
                "takes": v["takes"],
                "highlight": v["bankroll"]["highlight"],
                "oos": v.get("oos"),
                "gate": v["bankroll"]["gate"].get("verdict"),
            }
            for v in ranked[:8]
        ],
        "conclusion_es": conclusion,
        "disclaimer_es": (
            "Simulación con cases reales + fricción. No posta. No cambia DNA live. "
            "No depositar por este informe."
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    VPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slim = {k: report[k] for k in report if k != "variants"}
    slim["variants_top20"] = [
        {
            "mode": v["mode"],
            "takes": v["takes"],
            "highlight": v["bankroll"]["highlight"],
            "oos": v.get("oos"),
            "gate_passed": v["bankroll"]["gate"].get("passed"),
            "gate": v["bankroll"]["gate"].get("verdict"),
        }
        for v in ranked[:20]
    ]
    path = OUT / f"sim_improve_{stamp}.json"
    path.write_text(json.dumps(slim, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
    md = render_md(report)
    (OUT / "LATEST.md").write_text(md, encoding="utf-8")
    (VPS / "SIM_GAINS_REPORT.md").write_text(md, encoding="utf-8")
    (VPS / "SIM_GAINS_REPORT.json").write_text(
        json.dumps(
            {
                "live_dna": {
                    "takes": live["takes"],
                    "highlight": live["bankroll"]["highlight"],
                    "gate": live["bankroll"]["gate"],
                    "oos": live.get("oos"),
                },
                "champion_paper": {
                    "mode": champ["mode"],
                    "takes": champ["takes"],
                    "highlight": champ["bankroll"]["highlight"],
                    "gate": champ["bankroll"]["gate"],
                    "oos": champ.get("oos"),
                },
                "research_champion": {
                    "mode": research_champ["mode"],
                    "takes": research_champ["takes"],
                    "highlight": research_champ["bankroll"]["highlight"],
                    "oos": research_champ.get("oos"),
                    "gate": research_champ["bankroll"]["gate"].get("verdict"),
                },
                "near_live_champion": (
                    {
                        "mode": near["mode"],
                        "takes": near["takes"],
                        "highlight": near["bankroll"]["highlight"],
                        "oos": near.get("oos"),
                    }
                    if near
                    else None
                ),
                "aggressive_paper": report.get("aggressive_paper"),
                "n_robust_eligible": report.get("n_robust_eligible"),
                "n_near_live_eligible": report.get("n_near_live_eligible"),
                "top8": report["top8"],
                "conclusion_es": conclusion,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if write_docs:
        DOCS.mkdir(parents=True, exist_ok=True)
        (DOCS / "SIM_GAINS_REPORT.md").write_text(md, encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-docs", action="store_true")
    ap.add_argument("--quick", action="store_true", help="Skip dense grid; named variants only")
    args = ap.parse_args()
    rep = run(write_docs=bool(args.write_docs), full_grid=not bool(args.quick))
    live = rep["live_dna"]
    champ = rep["champion_paper"]
    research = rep.get("research_champion") or champ
    near = rep.get("near_live_champion")
    agr = rep.get("aggressive_paper")
    print(
        json.dumps(
            {
                "n_cases": rep["n_cases"],
                "n_paper_modes": rep["n_paper_modes"],
                "live_dna": {
                    "takes": live["takes"],
                    "highlight": live["bankroll"]["highlight"],
                    "gate": live["bankroll"]["gate"].get("verdict"),
                    "passed": live["bankroll"]["gate"].get("passed"),
                    "oos_base100": ((live.get("oos") or {}).get("highlight") or {}).get("base100"),
                },
                "champion_operational": {
                    "mode": champ["mode"],
                    "takes": champ["takes"],
                    "base100": (champ["bankroll"]["highlight"].get("base100") or {}).get("pnl"),
                },
                "research_champion": {
                    "mode": research["mode"],
                    "takes": research["takes"],
                    "base100": (research["bankroll"]["highlight"].get("base100") or {}).get("pnl"),
                    "oos_base100": (
                        ((research.get("oos") or {}).get("highlight") or {}).get("base100") or {}
                    ).get("pnl"),
                },
                "near_live_champion": (
                    {
                        "mode": near["mode"],
                        "takes": near["takes"],
                        "base100": (near["bankroll"]["highlight"].get("base100") or {}).get("pnl"),
                    }
                    if near
                    else None
                ),
                "aggressive_paper": agr,
                "conclusion_es": rep["conclusion_es"],
            },
            indent=2,
        )
    )
    h = live["bankroll"]["highlight"]
    ok = bool(
        ((h.get("base25") or {}).get("pnl") or 0) > 0
        or ((h.get("base100") or {}).get("pnl") or 0) > 0
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
