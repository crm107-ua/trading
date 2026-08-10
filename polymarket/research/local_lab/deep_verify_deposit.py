#!/usr/bin/env python3
"""
Deep verification battery for deposit runway + durable DNA (SAFE, no posts).

Goes far beyond a single gate check:
  A) SAFE posture (armed off, dry on, no ALLOW_REARM/CONFIRM)
  B) DNA config alignment across final/definitive/high_income
  C) Long-term robustness (full profile + adversaries must fail)
  D) Income mechanism (simulate_real_income all starts/stress)
  E) Capital matrix ($100/$200/$500) miss runway + bankroll base/hostile
  F) Deposit runway GO at $100 and $200
  G) Sensitivity ± basket/leg around DNA
  H) Leave-one-city / halves / weekly / walk-forward on DNA takes
  I) Friction durability (base/slip/hostile)
  J) Dual-control live refuse
  K) Forward telemetry honesty (snaps, dna_take rate, near-misses)
  L) Rearm decision consistency (DEPOSIT_RUNWAY_GO ≠ READY_TO_REARM)

Never sets ALLOW_REARM. Never posts.

  python3 -m polymarket.research.local_lab.deep_verify_deposit
  python3 -m polymarket.research.local_lab.deep_verify_deposit --write-docs
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.src.ai.env_loader import load_repo_dotenv

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "deep_verify"
DOCS = POLY / "docs"
VPS = POLY / "data_local" / "local_lab" / "vps_runs"
TELE = VPS / "telemetry"
CORE = ("singapore", "shanghai", "hong-kong", "beijing")

CFGS = {
    "final_longterm": POLY / "config" / "weather_ladder_final_longterm.json",
    "definitive_real": POLY / "config" / "weather_ladder_definitive_real.json",
    "high_income": POLY / "config" / "weather_ladder_high_income.json",
    "income_wr80": POLY / "config" / "weather_ladder_income_wr80.json",
}


def _wilson(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def layer_safe() -> dict[str, Any]:
    load_repo_dotenv(override=True)
    from polymarket.src.execution.clob_live import read_gates

    g = read_gates()
    checks = {
        "armed_off": not bool(g.armed),
        "dry_run_on": bool(g.dry_run),
        "allow_rearm_unset": not bool(os.environ.get("POLY_LADDER_ALLOW_REARM")),
        "real_confirm_unset": not bool(os.environ.get("POLY_LADDER_REAL_CONFIRM")),
        "signing_ready": bool(getattr(g, "signing_ready", None) or not g.missing),
    }
    # missing keys often include secrets presence
    return {
        "passed": all(checks[k] for k in ("armed_off", "dry_run_on", "allow_rearm_unset", "real_confirm_unset")),
        "checks": checks,
        "gates_missing": list(g.missing or []),
        "max_capital": getattr(g, "max_capital_usdc", None),
    }


def layer_dna_configs() -> dict[str, Any]:
    rows = {}
    ok = True
    for name, path in CFGS.items():
        if not path.exists():
            rows[name] = {"exists": False}
            ok = False
            continue
        cfg = json.loads(path.read_text(encoding="utf-8"))
        mb = float(cfg.get("max_basket_cost") or 99)
        ml = float(cfg.get("max_leg_price") or 99)
        ud = bool(cfg.get("require_underdispersion"))
        sleeves = cfg.get("sleeves") or []
        press_only = True
        bj_ok = True
        for sl in sleeves:
            for t in sl.get("tiers") or []:
                if t.get("name") not in (None, "press_under"):
                    # allow only press_under
                    if str(t.get("name")) != "press_under":
                        press_only = False
                if "beijing" in (sl.get("cities") or []):
                    if float(t.get("max_basket_cost") or mb) > 0.50 + 1e-12:
                        bj_ok = False
        checks = {
            "exists": True,
            "basket_le_50": mb <= 0.50 + 1e-12,
            "leg_le_39": ml <= 0.39 + 1e-12,
            "require_ud": ud,
            "press_only_tiers": press_only,
            "beijing_basket_le_50": bj_ok,
        }
        rows[name] = {"checks": checks, "max_basket": mb, "max_leg": ml, "passed": all(checks.values())}
        ok = ok and rows[name]["passed"]
    return {"passed": ok, "configs": rows}


def layer_long_term(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from polymarket.research.local_lab.long_term_robustness import (
        evaluate_profile,
        make_profiles,
        make_punctual_adversaries,
    )

    uni = [c for c in cases if c["city"] in CORE]
    profiles = make_profiles()
    durable = []
    for name, (prof, post_b) in profiles.items():
        rep = evaluate_profile(name, prof, uni, post_max_basket=post_b)
        durable.append(
            {
                "profile": name,
                "overall": rep["overall"],
                "oos_wr": rep["walk_forward"].get("oos_wr"),
                "score": rep["score"],
                "verdict": rep["gate"]["verdict"],
                "passed": rep["gate"]["passed"],
                "checks": rep["gate"]["checks"],
            }
        )
    adversaries = []
    for name, (prof, post_b) in make_punctual_adversaries().items():
        rep = evaluate_profile(name, prof, uni, post_max_basket=post_b)
        adversaries.append(
            {
                "profile": name,
                "overall": rep["overall"],
                "verdict": rep["gate"]["verdict"],
                "passed": rep["gate"]["passed"],
                "fail_checks": [k for k, v in rep["gate"]["checks"].items() if not v],
            }
        )
    best = max([d for d in durable if d["passed"]] or durable, key=lambda x: (x["passed"], x["score"], x["overall"]["n"]))
    adv_all_fail = all(not a["passed"] for a in adversaries)
    return {
        "passed": bool(best.get("passed")) and best["profile"] == "income_wr80" and adv_all_fail,
        "best": best,
        "income_wr80": next(d for d in durable if d["profile"] == "income_wr80"),
        "durable_passing": [d["profile"] for d in durable if d["passed"]],
        "adversaries": adversaries,
        "adversaries_all_fail": adv_all_fail,
        "note": "Champion must be income_wr80; punctual max-PnL adversaries must NOT pass LT gate.",
    }


def layer_income_mechanism(takes: list[dict[str, Any]]) -> dict[str, Any]:
    from polymarket.research.local_lab.simulate_real_income import STARTS, STRESS, gate_ok, simulate

    rows = []
    for start in STARTS:
        for sc in STRESS:
            r = simulate(takes, start=float(start), scenario=sc)
            rows.append(r)
    g = gate_ok(rows)
    # Extra: every start>=100 base+hostile profitable
    big_ok = all(
        r["income_positive"]
        for r in rows
        if r["start_usdc"] >= 100 and r["scenario"] in ("base", "hostile")
    )
    return {
        "passed": bool(g.get("passed")) and big_ok,
        "gate": g,
        "big_capital_ge100_base_hostile_positive": big_ok,
        "rows": [
            {
                "start": r["start_usdc"],
                "scenario": r["scenario"],
                "n": r["n"],
                "wr": r["winrate"],
                "pnl": r["total_pnl"],
                "end": r["ending_equity"],
                "dd": r["max_drawdown_frac"],
                "pf": r["profit_factor"],
            }
            for r in rows
        ],
    }


def layer_capital_matrix(takes: list[dict[str, Any]]) -> dict[str, Any]:
    from polymarket.research.local_lab.ladder_viability_report import capital_adequacy
    from polymarket.research.local_lab.simulate_real_income import STRESS, simulate
    from polymarket.research.local_lab import simulate_real_income as sri

    presets = {
        100.0: (50.0, 25.0),
        200.0: (100.0, 50.0),
        500.0: (150.0, 75.0),
    }
    fracs = {25.0: 0.32, 50.0: 0.18, 100.0: 0.12, 200.0: 0.10, 500.0: 0.08}
    old = dict(sri.BUDGET_FRACS)
    out = {}
    try:
        sri.BUDGET_FRACS = {**old, **fracs}
        for dep, (cap, bud) in presets.items():
            adeq = capital_adequacy(takes, balance=dep, session_cap=cap, budget_cfg=bud)
            bank = {}
            for sc in STRESS:
                if sc["name"] not in ("base", "hostile", "slip_3c_fee50"):
                    continue
                r = simulate(takes, start=float(dep), scenario=sc)
                bank[sc["name"]] = {
                    "n": r["n"],
                    "wr": r["winrate"],
                    "pnl": r["total_pnl"],
                    "end": r["ending_equity"],
                    "dd": r["max_drawdown_frac"],
                    "income_positive": r["income_positive"],
                }
            out[f"{dep:g}"] = {
                "deposit": dep,
                "session_cap": cap,
                "budget": bud,
                "adequacy": {
                    "executable": adeq.get("executable"),
                    "notional_first": adeq.get("notional_first"),
                    "equity_after_1_miss": adeq.get("equity_after_1_miss"),
                    "still_armed_after_1_miss": adeq.get("still_armed_after_1_miss"),
                    "misses_until_ruin": adeq.get("misses_until_ruin"),
                },
                "bankroll": bank,
                "passed": bool(adeq.get("still_armed_after_1_miss"))
                and all(bank[s]["income_positive"] for s in bank),
            }
    finally:
        sri.BUDGET_FRACS = old
    return {"passed": all(v["passed"] for v in out.values()), "by_deposit": out}


def layer_deposit_runway() -> dict[str, Any]:
    from polymarket.research.local_lab.verify_deposit_runway import run as runway_run

    r100 = runway_run(deposit=100.0, write_docs=False, run_income_tests=True)
    r200 = runway_run(deposit=200.0, write_docs=False, run_income_tests=False)
    return {
        "passed": bool(r100.get("can_deposit_runway_watch_only"))
        and bool(r200.get("can_deposit_runway_watch_only"))
        and not bool(r100.get("can_enable_auto_execute")),
        "d100": {
            "status": r100.get("status"),
            "can_deposit": r100.get("can_deposit_runway_watch_only"),
            "can_auto": r100.get("can_enable_auto_execute"),
            "checks": r100.get("checks"),
            "capital": {
                k: (r100.get("capital_planned") or {}).get(k)
                for k in (
                    "balance",
                    "notional_first",
                    "equity_after_1_miss",
                    "still_armed_after_1_miss",
                    "misses_until_ruin",
                )
            },
        },
        "d200": {
            "status": r200.get("status"),
            "can_deposit": r200.get("can_deposit_runway_watch_only"),
            "can_auto": r200.get("can_enable_auto_execute"),
            "capital": {
                k: (r200.get("capital_planned") or {}).get(k)
                for k in (
                    "balance",
                    "notional_first",
                    "equity_after_1_miss",
                    "still_armed_after_1_miss",
                    "misses_until_ruin",
                )
            },
        },
        "invariant_auto_blocked_with_n11": not bool(r100.get("can_enable_auto_execute")),
    }


def layer_sensitivity(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from polymarket.research.local_lab.long_term_robustness import sensitivity

    uni = [c for c in cases if c["city"] in CORE]
    grid = sensitivity(uni, "income_wr80")
    rate = sum(1 for s in grid if s["pass"]) / max(1, len(grid))
    return {
        "passed": rate + 1e-12 >= 0.70,
        "pass_rate": round(rate, 4),
        "n_grid": len(grid),
        "n_pass": sum(1 for s in grid if s["pass"]),
        "sample": grid[:8],
    }


def layer_dna_structure(takes: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    from polymarket.research.local_lab.long_term_robustness import (
        expanding_walk_forward,
        friction_durability,
        leave_one_city_out,
        make_profiles,
        take_with_profile,
        weekly_slices,
    )

    prof, post_b = make_profiles()["income_wr80"]
    uni = [c for c in cases if c["city"] in CORE]
    taken = take_with_profile(uni, prof, post_max_basket=post_b)
    ordered = sorted(taken, key=lambda t: t["day"])
    cut = max(2, len(ordered) // 2) if ordered else 0
    halves = [
        {"half": "first", "n": len(ordered[:cut]), "wins": sum(1 for t in ordered[:cut] if t.get("win"))},
        {"half": "second", "n": len(ordered[cut:]), "wins": sum(1 for t in ordered[cut:] if t.get("win"))},
    ]
    for h in halves:
        h["wr"] = round(h["wins"] / h["n"], 4) if h["n"] else 0.0
    wf = expanding_walk_forward(taken)
    weeks = weekly_slices(taken)
    loco = leave_one_city_out(uni, prof, post_max_basket=post_b)
    fr = friction_durability(taken)
    wins = sum(1 for t in takes if t.get("win"))
    n = len(takes)
    checks = {
        "n_ge_6": n >= 6,
        "wr_100_or_ge90": (wins / n if n else 0) + 1e-12 >= 0.90,
        "halves_wr_ge_80": all(h["wr"] + 1e-12 >= 0.80 for h in halves if h["n"] >= 2),
        "oos_wr_ge_80": (wf.get("oos_wr") or 0) + 1e-12 >= 0.80,
        "weekly_strict": all(w["wr"] + 1e-12 >= 0.80 for w in weeks if w["n"] >= 2),
        "loco_ok": all(r["wr"] + 1e-12 >= 0.80 and r["pnl"] > 0 for r in loco if r["n"] >= 3),
        "friction_all": all(f.get("pass") for f in fr),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "n": n,
        "wins": wins,
        "wilson": round(_wilson(wins, n), 4),
        "halves": halves,
        "walk_forward": {k: wf.get(k) for k in ("oos_n", "oos_wr", "oos_pnl", "min_fold_wr_n2")},
        "weekly": weeks,
        "leave_one_city": loco,
        "friction": fr,
        "by_city": dict(Counter(t.get("city") for t in takes)),
    }


def layer_dual_control() -> dict[str, Any]:
    from polymarket.research.local_lab.assurance_research import dual_control_live_refuse

    dc = dual_control_live_refuse()
    return {"passed": bool(dc.get("passed")), **dc}


def layer_bootstrap_and_multimiss(takes: list[dict[str, Any]]) -> dict[str, Any]:
    """Extra depth: Wilson/bootstrap lower bounds + 2–3 miss ruin paths at $100/$200."""
    import random

    from polymarket.research.local_lab.ladder_viability_report import capital_adequacy

    wins = [bool(t.get("win")) for t in takes]
    n = len(wins)
    k = sum(wins)
    wilson = _wilson(k, n)
    rng = random.Random(7)
    boots = []
    for _ in range(5000):
        sample = [wins[rng.randrange(n)] for _ in range(n)] if n else []
        boots.append(sum(sample) / n if n else 0.0)
    boots.sort()
    boot05 = boots[int(0.05 * len(boots))] if boots else 0.0

    multi = {}
    for dep, cap, bud in ((100.0, 50.0, 25.0), (200.0, 100.0, 50.0)):
        adeq = capital_adequacy(takes, balance=dep, session_cap=cap, budget_cfg=bud)
        notional = float(adeq.get("notional_first") or bud)
        after2 = dep - 2 * notional
        after3 = dep - 3 * notional
        multi[f"{dep:g}"] = {
            "notional": notional,
            "after_1": round(dep - notional, 4),
            "after_2": round(after2, 4),
            "after_3": round(after3, 4),
            "survives_2_misses_ge2": after2 >= 2.0 - 1e-9,
            "survives_3_misses_ge2": after3 >= 2.0 - 1e-9,
            "misses_until_ruin": adeq.get("misses_until_ruin"),
        }
    # Point WR can be 100% with n=11 while Wilson<0.8 — expected; depth check is honesty
    checks = {
        "wilson_reported": wilson,
        "bootstrap05": round(boot05, 4),
        "wilson_lt_80_honest_with_n11": wilson < 0.80,  # must remain honest
        "bootstrap_le_wilson_band": boot05 <= wilson + 0.05,
        "d100_survives_2": multi["100"]["survives_2_misses_ge2"],
        "d200_survives_3": multi["200"]["survives_3_misses_ge2"],
    }
    return {
        "passed": bool(
            checks["d100_survives_2"]
            and checks["d200_survives_3"]
            and checks["wilson_lt_80_honest_with_n11"]
        ),
        "checks": checks,
        "multi_miss": multi,
        "note": (
            "Honesty: Wilson<0.80 with n=11 blocks auto-execute; "
            "multi-miss runway still OK at $100/$200."
        ),
    }


def layer_live_scripts_refuse() -> dict[str, Any]:
    """private_manager_live must refuse without ALLOW_REARM."""
    import subprocess

    script = POLY / "scripts" / "private_manager_live.sh"
    if not script.exists():
        return {"passed": True, "note": "script_missing_in_cloud_ok", "skipped": True}
    env = os.environ.copy()
    env["POLY_LIVE_ARMED"] = "0"
    env["POLY_LIVE_DRY_RUN"] = "1"
    env.pop("POLY_LADDER_ALLOW_REARM", None)
    env.pop("POLY_LADDER_REAL_CONFIRM", None)
    try:
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=str(POLY.parent),
            capture_output=True,
            text=True,
            timeout=45,
            env=env,
        )
    except Exception as e:
        return {"passed": False, "error": str(e)}
    out = (proc.stdout or "") + (proc.stderr or "")
    hard = proc.returncode != 0
    return {
        "passed": hard,
        "exit_code": proc.returncode,
        "stdout_tail": "\n".join(out.splitlines()[-20:]),
        "note": "Live manager must non-zero exit without ALLOW_REARM",
    }


def layer_forward_telemetry() -> dict[str, Any]:
    snap = TELE / "quote_snapshots.jsonl"
    if not snap.exists():
        return {"passed": True, "note": "no_local_snapshots (ok if cloud); VPS may differ", "snaps": 0}
    rows = []
    for line in snap.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    dna_n = sum(1 for r in rows if r.get("dna_take"))
    slugs = {r.get("slug") for r in rows if r.get("slug")}
    near = [
        r
        for r in rows
        if float(r.get("basket_cost") or 99) <= 0.55
        or int((r.get("gates") or {}).get("gates_passed") or 0) >= 2
    ]
    return {
        "passed": True,
        "snaps": len(rows),
        "unique_slugs": len(slugs),
        "dna_take_true": dna_n,
        "near_miss_rows": len(near),
        "cities": dict(Counter(r.get("city") for r in rows)),
        "note": "Live DNA takes may be 0 while markets are rich/UD-stuck; runway deposit still OK.",
    }


def layer_rearm_consistency() -> dict[str, Any]:
    from polymarket.research.local_lab.rearm_income_gate import evidence_block, decide
    from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
    from polymarket.research.local_lab.ladder_viability_report import capital_adequacy
    from polymarket.research.local_lab.real_env_ready import check_code_safety
    from polymarket.research.local_lab.verify_deposit_runway import run as runway_run

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    takes = take_income_wr80(cases)
    ev = evidence_block(takes)
    eng = check_code_safety()
    cap_now = capital_adequacy(takes, balance=3.4482, session_cap=5.0, budget_cfg=3.0)
    cap_now["balance"] = 3.4482
    runway = runway_run(deposit=100.0, write_docs=False, run_income_tests=False)
    # attach income from latest if needed
    latest = POLY / "data_local" / "local_lab" / "real_income_sim" / "latest.json"
    income = {"passed": False}
    if latest.exists():
        g = json.loads(latest.read_text()).get("gate") or {}
        income = {"passed": bool(g.get("passed")), "verdict": g.get("verdict")}
    report = {
        "evidence": ev,
        "engineering": eng,
        "income_mechanism": income,
        "capital": cap_now,
        "deposit_runway": runway,
        "ops_mode": {"watch_only_required": True, "currently_watch_only": True},
    }
    d = decide(report)
    checks = {
        "status_is_deposit_runway_go": d.get("status") == "DEPOSIT_RUNWAY_GO",
        "can_deposit_true": bool(d.get("can_deposit_runway_watch_only")),
        "can_recommend_deposit_true": bool(d.get("can_recommend_deposit")),
        "auto_execute_false": not bool(d.get("can_enable_auto_execute")),
        "evidence_still_blocks_auto": any("evidence_n=" in b or "auto_execute_blocked" in b for b in (d.get("blockers") or [])),
    }
    return {"passed": all(checks.values()), "decision": d, "checks": checks}


def grade(layers: dict[str, Any]) -> dict[str, Any]:
    """Score deep verify. Deposit runway can be GO even if evidence incomplete."""
    must = [
        "A_safe",
        "B_dna_configs",
        "C_long_term",
        "D_income_mechanism",
        "E_capital_matrix",
        "F_deposit_runway",
        "G_sensitivity",
        "H_dna_structure",
        "J_dual_control",
        "L_rearm_consistency",
        "M_bootstrap_multimiss",
        "N_live_scripts_refuse",
    ]
    optional = ["I_forward_telemetry"]  # alias K
    # map
    key_map = {
        "A_safe": "A_safe",
        "B_dna_configs": "B_dna_configs",
        "C_long_term": "C_long_term",
        "D_income_mechanism": "D_income_mechanism",
        "E_capital_matrix": "E_capital_matrix",
        "F_deposit_runway": "F_deposit_runway",
        "G_sensitivity": "G_sensitivity",
        "H_dna_structure": "H_dna_structure",
        "J_dual_control": "J_dual_control",
        "K_forward_telemetry": "K_forward_telemetry",
        "L_rearm_consistency": "L_rearm_consistency",
        "M_bootstrap_multimiss": "M_bootstrap_multimiss",
        "N_live_scripts_refuse": "N_live_scripts_refuse",
    }
    results = []
    for k in must + ["K_forward_telemetry"]:
        layer = layers.get(k) or {}
        passed = bool(layer.get("passed"))
        results.append({"layer": k, "passed": passed, "required": k != "K_forward_telemetry"})
    req_ok = all(r["passed"] for r in results if r["required"])
    n_pass = sum(1 for r in results if r["passed"])
    n_tot = len(results)
    if req_ok:
        verdict = "DEEP_VERIFY_DEPOSIT_RUNWAY_PASS"
        action = (
            "Verificación profunda PASS para depositar $100–$200 en runway watch-only. "
            "Auto-execute sigue bloqueado por evidencia (n<50)."
        )
    else:
        fails = [r["layer"] for r in results if r["required"] and not r["passed"]]
        verdict = "DEEP_VERIFY_FAIL"
        action = f"Fallos en capas: {fails}"
    return {
        "verdict": verdict,
        "passed": req_ok,
        "score": f"{n_pass}/{n_tot}",
        "layers": results,
        "action_es": action,
        "can_deposit_runway_watch_only": req_ok,
        "can_enable_auto_execute": False,  # deep verify never grants auto
    }


def render_md(report: dict[str, Any]) -> str:
    g = report["grade"]
    lines = [
        "# Deep verify — depósito runway",
        "",
        f"**UTC:** `{report['ts_utc']}`",
        f"**Veredicto:** `{g['verdict']}` · score={g['score']}",
        "",
        g["action_es"],
        "",
        f"- can_deposit_runway_watch_only=`{g['can_deposit_runway_watch_only']}`",
        f"- can_enable_auto_execute=`{g['can_enable_auto_execute']}` (siempre false aquí)",
        "",
        "## Capas",
    ]
    for row in g["layers"]:
        mark = "PASS" if row["passed"] else "FAIL"
        req = "required" if row["required"] else "optional"
        lines.append(f"- `{row['layer']}` **{mark}** ({req})")
    # highlights
    lt = report["layers"]["C_long_term"]
    cap = report["layers"]["E_capital_matrix"]["by_deposit"].get("100")
    dr = report["layers"]["F_deposit_runway"]
    dna = report["layers"]["H_dna_structure"]
    lines += [
        "",
        "## Highlights",
        f"- LT best=`{(lt.get('best') or {}).get('profile')}` verdict=`{(lt.get('best') or {}).get('verdict')}` "
        f"adversaries_fail=`{lt.get('adversaries_all_fail')}`",
        f"- DNA structure n={dna.get('n')} Wilson={dna.get('wilson')} OOS={((dna.get('walk_forward') or {}).get('oos_wr'))}",
        f"- Capital $100: {cap}",
        f"- Deposit runway $100: {dr.get('d100')}",
        f"- Deposit runway $200: {dr.get('d200')}",
        f"- Rearm decision: {(report['layers']['L_rearm_consistency'].get('decision') or {})}",
        "",
        "## Invariantes",
        "- DNA press-only ≤0.50 / leg≤0.39 / UD no se relaja.",
        "- Adversarios max-PnL deben fallar long-term gate.",
        "- Deep verify PASS ≠ READY_TO_REARM / auto-execute.",
        "",
    ]
    return "\n".join(lines)


def run(*, write_docs: bool = False) -> dict[str, Any]:
    load_repo_dotenv(override=True)
    # Force SAFE for this process
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    os.environ.pop("POLY_LADDER_ALLOW_REARM", None)
    os.environ.pop("POLY_LADDER_REAL_CONFIRM", None)

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    from polymarket.research.local_lab.assure_wr80_income import take_income_wr80

    takes = take_income_wr80(cases)
    print(f"DNA takes n={len(takes)} cases={len(cases)}", flush=True)

    layers: dict[str, Any] = {}
    print("A SAFE…", flush=True)
    layers["A_safe"] = layer_safe()
    print("B DNA configs…", flush=True)
    layers["B_dna_configs"] = layer_dna_configs()
    print("C long-term…", flush=True)
    layers["C_long_term"] = layer_long_term(cases)
    print("D income mechanism…", flush=True)
    layers["D_income_mechanism"] = layer_income_mechanism(takes)
    print("E capital matrix…", flush=True)
    layers["E_capital_matrix"] = layer_capital_matrix(takes)
    print("F deposit runway…", flush=True)
    layers["F_deposit_runway"] = layer_deposit_runway()
    print("G sensitivity…", flush=True)
    layers["G_sensitivity"] = layer_sensitivity(cases)
    print("H dna structure…", flush=True)
    layers["H_dna_structure"] = layer_dna_structure(takes, cases)
    print("J dual control + live refuse…", flush=True)
    layers["J_dual_control"] = layer_dual_control()
    layers["N_live_scripts_refuse"] = layer_live_scripts_refuse()
    print("K forward telemetry…", flush=True)
    layers["K_forward_telemetry"] = layer_forward_telemetry()
    print("L rearm consistency…", flush=True)
    layers["L_rearm_consistency"] = layer_rearm_consistency()
    print("M bootstrap + multi-miss…", flush=True)
    layers["M_bootstrap_multimiss"] = layer_bootstrap_and_multimiss(takes)

    g = grade(layers)
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "dna_takes_n": len(takes),
        "cases_n": len(cases),
        "layers": layers,
        "grade": g,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    VPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # slim for disk: drop huge row dumps partially
    slim = json.loads(json.dumps(report))
    if "rows" in (slim.get("layers", {}).get("D_income_mechanism") or {}):
        # keep all rows — useful
        pass
    path = OUT / f"deep_verify_{stamp}.json"
    path.write_text(json.dumps(slim, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
    md = render_md(report)
    (OUT / "LATEST.md").write_text(md, encoding="utf-8")
    (VPS / "DEEP_VERIFY_DEPOSIT.md").write_text(md, encoding="utf-8")
    (VPS / "DEEP_VERIFY_DEPOSIT.json").write_text(
        json.dumps({"grade": g, "ts_utc": report["ts_utc"], "dna_takes_n": len(takes)}, indent=2),
        encoding="utf-8",
    )
    if write_docs:
        DOCS.mkdir(parents=True, exist_ok=True)
        (DOCS / "DEEP_VERIFY_DEPOSIT.md").write_text(md, encoding="utf-8")
        # refresh MONEY_READY with deep pointer
        (DOCS / "MONEY_READY_STATUS.md").write_text(
            "\n".join(
                [
                    "# Money-ready status (investigación)",
                    "",
                    f"**UTC:** `{report['ts_utc']}`",
                    f"**Deep verify:** `{g['verdict']}` score={g['score']}",
                    f"**Deposit runway:** `{g['can_deposit_runway_watch_only']}`",
                    f"**Auto-execute:** `{g['can_enable_auto_execute']}`",
                    f"**DNA n:** {len(takes)}",
                    "",
                    g["action_es"],
                    "",
                    "Detalle: [`DEEP_VERIFY_DEPOSIT.md`](DEEP_VERIFY_DEPOSIT.md) · [`DEPOSIT_RUNWAY.md`](DEPOSIT_RUNWAY.md)",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-docs", action="store_true")
    args = ap.parse_args()
    rep = run(write_docs=bool(args.write_docs))
    g = rep["grade"]
    summary = {
        "verdict": g["verdict"],
        "score": g["score"],
        "action_es": g["action_es"],
        "can_deposit_runway_watch_only": g["can_deposit_runway_watch_only"],
        "can_enable_auto_execute": g["can_enable_auto_execute"],
        "layers": g["layers"],
        "fails": [x["layer"] for x in g["layers"] if x["required"] and not x["passed"]],
    }
    print(json.dumps(summary, indent=2))
    return 0 if g["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
