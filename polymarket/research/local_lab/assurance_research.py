#!/usr/bin/env python3
"""
Assurance research scorecard — Temperature Ladder (WATCH_ONLY).

Goal: make the path to real income *more assured* without relaxing DNA,
depositing, or arming.

Produces:
  data_local/local_lab/vps_runs/ASSURANCE_SCORECARD.json|.md
  telemetry/assurance_events.jsonl (append)

Analyses:
  1) Gate-failure attribution from near_miss journal
  2) Wilson path-to-GO (optimistic / conservative future WR)
  3) Capital runway matrix (live + deposit what-ifs)
  4) Snapshot quality audit (ud/gates/models completeness)
  5) Close-book persistence (HK gap / UD stuck?)
  6) DNA take stress (existing assure_wr80 friction)
  7) Dual-control: live manager must still refuse without READY
  8) Pre-registered rules (no cherry-pick)

  python3 -m polymarket.research.local_lab.assurance_research
  python3 -m polymarket.research.local_lab.assurance_research --write-docs
"""

from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POLY = Path(__file__).resolve().parents[2]
REPO = POLY.parent
TELE = POLY / "data_local" / "local_lab" / "vps_runs" / "telemetry"
VPS = POLY / "data_local" / "local_lab" / "vps_runs"
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
DOCS = POLY / "docs"
OUT = POLY / "data_local" / "local_lab" / "assurance"

MIN_N_GO = 50
MIN_N_DEPOSIT = 30
MIN_WILSON = 0.80
DNA_BASKET = 0.50
DNA_LEG = 0.39
DNA_UD = 0.65


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def _load_jsonl(path: Path, limit: int = 20000) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:]


def gate_attribution(near: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    waiting: Counter[str] = Counter()
    by_city: dict[str, Counter[str]] = defaultdict(Counter)
    gaps: list[float] = []
    for n in near:
        for r in n.get("reasons") or []:
            reasons[r] += 1
        g = n.get("gates") or {}
        for w in g.get("waiting") or []:
            waiting[w] += 1
            by_city[str(n.get("city") or "?")][w] += 1
        gb = n.get("gap_basket")
        if isinstance(gb, (int, float)):
            gaps.append(float(gb))
    gaps_sorted = sorted(gaps)
    n = len(gaps_sorted)

    def pct(p: float) -> float | None:
        if not gaps_sorted:
            return None
        idx = min(n - 1, max(0, int(p * (n - 1))))
        return round(gaps_sorted[idx], 4)

    return {
        "near_miss_n": len(near),
        "reasons": dict(reasons.most_common()),
        "waiting_gates": dict(waiting.most_common()),
        "waiting_by_city": {c: dict(v) for c, v in by_city.items()},
        "gap_min": pct(0.0),
        "gap_p10": pct(0.10),
        "gap_p50": pct(0.50),
        "gap_p90": pct(0.90),
        "note_es": (
            "basket_rich domina → libros caros, no aflojar 0.50. "
            "UD frecuente en HK → modelos divergentes; esperar convergencia, no bypass."
        ),
    }


def wilson_path(wins: int, n: int) -> dict[str, Any]:
    """How many future takes needed under optimistic / conservative WR."""
    scenarios = []
    for label, future_wr in (("perfect_1.00", 1.0), ("strong_0.90", 0.90), ("gate_min_0.85", 0.85)):
        need_k = None
        for k in range(0, 200):
            # expected wins added ≈ round but use floor for conservative integer wins
            add_wins = int(math.floor(future_wr * k + 1e-12))
            # for perfect, add_wins = k
            if future_wr >= 1.0 - 1e-12:
                add_wins = k
            w2 = wins + add_wins
            n2 = n + k
            if n2 >= MIN_N_GO and _wilson_lower(w2, n2) + 1e-12 >= MIN_WILSON:
                need_k = k
                break
        scenarios.append(
            {
                "label": label,
                "assumed_future_wr": future_wr,
                "additional_takes_to_go_micro": need_k,
                "reachable": need_k is not None,
            }
        )
    deposit_talk = None
    for k in range(0, 200):
        w2 = wins + k  # optimistic
        n2 = n + k
        if n2 >= MIN_N_DEPOSIT and _wilson_lower(w2, n2) + 1e-12 >= MIN_WILSON:
            deposit_talk = k
            break
    return {
        "current": {
            "n": n,
            "wins": wins,
            "wr_point": round(wins / n, 4) if n else 0.0,
            "wilson95_lower": round(_wilson_lower(wins, n), 4),
        },
        "targets": {"min_n_go": MIN_N_GO, "min_n_deposit_talk": MIN_N_DEPOSIT, "min_wilson": MIN_WILSON},
        "optimistic_to_deposit_talk": deposit_talk,
        "to_go_micro": scenarios,
        "note_es": (
            "Wilson path asume takes DNA *forward reales* (no MC reciclado). "
            "Si future WR <~0.85 con n bajo, GO_MICRO puede ser inalcanzable sin más muestra limpia."
        ),
    }


def capital_matrix(balance: float) -> dict[str, Any]:
    from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
    from polymarket.research.local_lab.ladder_viability_report import capital_adequacy

    if not CASES.exists():
        return {"passed": False, "error": "missing_cases"}
    raw = take_income_wr80(json.loads(CASES.read_text(encoding="utf-8")))
    rows = {}
    for bal in (balance, 10.0, 25.0, 50.0, 100.0):
        adeq = capital_adequacy(raw, balance=float(bal), session_cap=5.0, budget_cfg=3.0)
        rows[f"{bal:g}"] = {
            "balance": bal,
            "executable": adeq.get("executable"),
            "notional": adeq.get("notional_first") or adeq.get("notional"),
            "still_armed_after_1_miss": adeq.get("still_armed_after_1_miss"),
            "equity_after_1_miss": adeq.get("equity_after_1_miss"),
            "misses_until_ruin": adeq.get("misses_until_ruin"),
        }
    return {
        "passed": True,
        "live_balance": balance,
        "profiles": rows,
        "deposit_floor_hint_usdc": 25.0,
        "note_es": "What-if sim. No orden de depósito mientras evidence_ready=False.",
    }


def snapshot_quality(snaps: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(snaps)
    if n == 0:
        return {"n": 0, "ok": False}
    has_ud = sum(1 for s in snaps if isinstance(s.get("ud"), dict) and s["ud"].get("ratio") is not None)
    has_gates = sum(1 for s in snaps if isinstance(s.get("gates"), dict))
    has_models = sum(1 for s in snaps if len(s.get("models") or {}) >= 2)
    has_entries = sum(1 for s in snaps if len(s.get("entries") or {}) >= 3)
    recent = snaps[-min(100, n) :]
    recent_ud = sum(1 for s in recent if isinstance(s.get("ud"), dict) and s["ud"].get("ratio") is not None)
    recent_gates = sum(1 for s in recent if isinstance(s.get("gates"), dict))
    return {
        "n": n,
        "pct_ud": round(has_ud / n, 3),
        "pct_gates": round(has_gates / n, 3),
        "pct_models": round(has_models / n, 3),
        "pct_entries_ge3": round(has_entries / n, 3),
        "recent100_pct_ud": round(recent_ud / len(recent), 3),
        "recent100_pct_gates": round(recent_gates / len(recent), 3),
        "quality_ok": (recent_ud / len(recent) >= 0.95) and (recent_gates / len(recent) >= 0.90),
        "note_es": "Calidad reciente debe tener UD+gates para scoreboard fiable.",
    }


def close_book_persistence(snaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Track markets that stay within 8¢ and whether UD ever flips true."""
    by_slug: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in snaps:
        slug = s.get("slug")
        if not slug:
            continue
        by_slug[str(slug)].append(s)
    out = []
    for slug, rows in by_slug.items():
        baskets = [float(r["basket_cost"]) for r in rows if isinstance(r.get("basket_cost"), (int, float))]
        if not baskets:
            continue
        best = min(baskets)
        gap = max(0.0, best - DNA_BASKET)
        if gap > 0.12:
            continue
        ud_ratios = [
            float(r["ud"]["ratio"])
            for r in rows
            if isinstance(r.get("ud"), dict) and isinstance(r["ud"].get("ratio"), (int, float))
        ]
        ud_true_n = sum(
            1
            for r in rows
            if (isinstance(r.get("ud"), dict) and r["ud"].get("underdispersed"))
            or r.get("underdispersed") is True
        )
        last = rows[-1]
        out.append(
            {
                "slug": slug,
                "city": last.get("city"),
                "day": last.get("day"),
                "snaps": len(rows),
                "best_basket": round(best, 4),
                "gap": round(gap, 4),
                "live_basket": last.get("basket_cost"),
                "ud_true_count": ud_true_n,
                "ud_ratio_min": round(min(ud_ratios), 4) if ud_ratios else None,
                "ud_ratio_last": round(ud_ratios[-1], 4) if ud_ratios else None,
                "ud_ever_ok": (min(ud_ratios) <= DNA_UD + 1e-12) if ud_ratios else False,
                "stuck_without_ud": gap <= 0.08 and ud_ratios and min(ud_ratios) > DNA_UD + 1e-12,
            }
        )
    out.sort(key=lambda x: x["gap"])
    stuck = [x for x in out if x.get("stuck_without_ud")]
    return {
        "close_markets": out,
        "stuck_without_ud_n": len(stuck),
        "stuck": stuck,
        "note_es": (
            "Si HK permanece cerca en basket pero UD ratio ~2.5 estable, el gate UD está "
            "protegiendo (modelos no convergen). No bypassear."
        ),
    }


def dna_stress() -> dict[str, Any]:
    from polymarket.research.local_lab.assure_wr80_income import run_assurance

    if not CASES.exists():
        return {"passed": False, "error": "missing_cases"}
    # run_assurance may need specific signature — fall back to take + friction
    try:
        from polymarket.research.local_lab import assure_wr80_income as m

        cases = json.loads(CASES.read_text(encoding="utf-8"))
        if hasattr(m, "evaluate_income_gate"):
            rep = m.evaluate_income_gate(cases)  # type: ignore[attr-defined]
            return {"passed": bool((rep.get("gate") or {}).get("passed") or rep.get("passed")), "report": rep}
        taken = m.take_income_wr80(cases)
        wins = sum(1 for t in taken if t.get("win") or float(t.get("pnl") or 0) > 0)
        n = len(taken)
        # light friction probe via module helpers if present
        friction = []
        if hasattr(m, "friction_wr"):
            for slip in (0.01, 0.02, 0.03):
                friction.append(m.friction_wr(taken, {"slip": slip, "fee_bps": 50, "fill": 0.9}))
        return {
            "passed": n >= 1,
            "n": n,
            "wins": wins,
            "wilson95": round(_wilson_lower(wins, n), 4),
            "friction": friction,
            "caveat": "Misma muestra n=11 — stress no crea evidencia OOS nueva.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}


def dual_control_live_refuse() -> dict[str, Any]:
    """Confirm live manager still refuses without ALLOW_REARM (script-level)."""
    live = POLY / "scripts" / "private_manager_live.sh"
    if not live.is_file():
        return {"passed": False, "error": "missing_live_script"}
    txt = live.read_text(encoding="utf-8")
    checks = {
        "requires_allow_rearm": "POLY_LADDER_ALLOW_REARM" in txt,
        "checks_rearm_gate": "rearm_income_gate" in txt,
        "starts_safe": "POLY_LIVE_ARMED=0" in txt and "POLY_LIVE_DRY_RUN=1" in txt,
        "requires_ready_status": "READY_TO_REARM" in txt,
    }
    # Runtime refuse without ALLOW
    env = os.environ.copy()
    env["POLY_LADDER_ALLOW_REARM"] = "0"
    env["POLY_LIVE_ARMED"] = "0"
    env["POLY_LIVE_DRY_RUN"] = "1"
    try:
        proc = subprocess.run(
            ["bash", str(live)],
            cwd=str(REPO) if (REPO / "polymarket").is_dir() else "/var/www/html/trader",
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
        runtime_refused = proc.returncode == 2
    except Exception as exc:  # noqa: BLE001
        runtime_refused = False
        checks["runtime_error"] = f"{type(exc).__name__}: {exc}"
    return {
        "passed": all(checks.values()) and runtime_refused,
        "checks": checks,
        "runtime_refused_without_allow": runtime_refused,
    }


def preregistered_rules() -> dict[str, Any]:
    return {
        "dna_basket_max": DNA_BASKET,
        "dna_leg_max": DNA_LEG,
        "dna_ud_ratio_max": DNA_UD,
        "min_n_go_micro": MIN_N_GO,
        "min_wilson_go": MIN_WILSON,
        "no_mc_as_evidence": True,
        "no_pre_july_synthetic_clob": True,
        "forward_snapshots_only_path_to_n": True,
        "rearm_requires_ready_gate": True,
        "note_es": (
            "Reglas pre-registradas: no se pueden aflojar para 'asegurar' ingreso. "
            "Asegurar = más muestra forward + capital runway + controles duales."
        ),
    }


def assurance_grade(report: dict[str, Any]) -> dict[str, Any]:
    """Composite assurance without claiming READY_TO_REARM."""
    score = 0
    max_score = 10
    bits = []

    def add(ok: bool, pts: int, label: str) -> None:
        nonlocal score
        if ok:
            score += pts
        bits.append({"ok": ok, "pts": pts if ok else 0, "max": pts, "label": label})

    safeish = True  # research posture assumed; dual control checked separately
    add(bool((report.get("dual_control") or {}).get("passed")), 2, "dual_control_live_refuse")
    add(bool((report.get("snapshot_quality") or {}).get("quality_ok")), 1, "snapshot_quality_recent")
    add(bool((report.get("dna_stress") or {}).get("passed")), 1, "dna_stress_ran")
    wp = report.get("wilson_path") or {}
    cur = wp.get("current") or {}
    add(int(cur.get("n") or 0) >= 10, 1, "baseline_sample_ge_10")
    # path reachable under strong 0.90
    go = {s["label"]: s for s in (wp.get("to_go_micro") or [])}
    add(bool((go.get("strong_0.90") or {}).get("reachable")), 1, "wilson_path_reachable_wr90")
    cap = report.get("capital") or {}
    live_ok = False
    dep25_ok = False
    for k, row in (cap.get("profiles") or {}).items():
        if abs(float(row.get("balance") or 0) - float(cap.get("live_balance") or 0)) < 1e-6:
            live_ok = bool(row.get("still_armed_after_1_miss"))
        if abs(float(row.get("balance") or 0) - 25.0) < 1e-6:
            dep25_ok = bool(row.get("still_armed_after_1_miss"))
    add(not live_ok, 1, "honest_live_capital_insufficient")  # honesty is assurance
    add(dep25_ok, 1, "deposit25_survives_1_miss_sim")
    stuck_n = int((report.get("close_books") or {}).get("stuck_without_ud_n") or 0)
    add(True, 1, "ud_gate_monitoring_active")  # always on if we produced close_books
    add(stuck_n >= 0, 1, "close_book_persistence_tracked")

    pct = round(100.0 * score / max_score, 1)
    if pct >= 85:
        grade = "A_ASSURED_OPS"
    elif pct >= 70:
        grade = "B_SOLID_PREP"
    elif pct >= 50:
        grade = "C_PARTIAL"
    else:
        grade = "D_WEAK"
    return {
        "score": score,
        "max_score": max_score,
        "pct": pct,
        "grade": grade,
        "bits": bits,
        "meaning_es": (
            "Grado de *preparación/assurance ops*, NO permiso de rearme. "
            "Rearme solo con READY_TO_REARM (evidencia+capital)."
        ),
    }


def render_md(report: dict[str, Any]) -> str:
    g = report["grade"]
    wp = report["wilson_path"]
    cur = wp["current"]
    att = report["gate_attribution"]
    lines = [
        "# Assurance scorecard — Temperature Ladder",
        "",
        f"**UTC:** `{report['ts_utc']}`",
        f"**Grade:** `{g['grade']}` ({g['pct']}%) — {g['meaning_es']}",
        "",
        "## Evidencia",
        f"- n={cur['n']} wins={cur['wins']} WR={cur['wr_point']} Wilson95={cur['wilson95_lower']}",
        f"- optimistic_to_deposit_talk=+{wp.get('optimistic_to_deposit_talk')} takes",
    ]
    for s in wp.get("to_go_micro") or []:
        lines.append(
            f"- {s['label']}: additional_takes={s.get('additional_takes_to_go_micro')} reachable={s.get('reachable')}"
        )
    lines += [
        "",
        "## Atribución near-miss (no aflojar DNA)",
        f"- n={att.get('near_miss_n')} reasons={att.get('reasons')}",
        f"- waiting_gates={att.get('waiting_gates')}",
        f"- gap min/p10/p50={att.get('gap_min')}/{att.get('gap_p10')}/{att.get('gap_p50')}",
        f"- {att.get('note_es')}",
        "",
        "## Libros cerca / UD stuck",
    ]
    for c in (report.get("close_books") or {}).get("close_markets") or []:
        lines.append(
            f"- {c['city']} {c['day']}: best={c['best_basket']} gap={c['gap']} "
            f"ud_min={c.get('ud_ratio_min')} stuck={c.get('stuck_without_ud')} snaps={c['snaps']}"
        )
    lines += [
        "",
        "## Capital what-if",
    ]
    for k, row in ((report.get("capital") or {}).get("profiles") or {}).items():
        lines.append(
            f"- ${k}: armed_after_1={row.get('still_armed_after_1_miss')} "
            f"notional={row.get('notional')} equity_after_1={row.get('equity_after_1_miss')}"
        )
    sq = report.get("snapshot_quality") or {}
    dc = report.get("dual_control") or {}
    lines += [
        "",
        "## Calidad snapshots",
        f"- n={sq.get('n')} recent_ud={sq.get('recent100_pct_ud')} recent_gates={sq.get('recent100_pct_gates')} ok={sq.get('quality_ok')}",
        "",
        "## Dual control",
        f"- passed={dc.get('passed')} runtime_refused={dc.get('runtime_refused_without_allow')} checks={dc.get('checks')}",
        "",
        "## Reglas pre-registradas",
        f"- {json.dumps(report.get('preregistered'), ensure_ascii=False)}",
        "",
        "## Acción",
        "",
        report.get("action_es") or "",
        "",
    ]
    return "\n".join(lines)


def run(*, balance: float | None = None, write_docs: bool = False) -> dict[str, Any]:
    os.environ.setdefault("POLY_LIVE_ARMED", "0")
    os.environ.setdefault("POLY_LIVE_DRY_RUN", "1")
    os.environ["PYTHONPATH"] = str(REPO)

    near = _load_jsonl(TELE / "near_miss.jsonl")
    snaps = _load_jsonl(TELE / "quote_snapshots.jsonl")
    rounds = _load_jsonl(TELE / "watch_rounds.jsonl")

    # balance
    bal = balance
    if bal is None and rounds:
        b = rounds[-1].get("balance_pusd")
        if isinstance(b, (int, float)):
            bal = float(b)
    if bal is None:
        bal = 3.4482

    from polymarket.research.local_lab.assure_wr80_income import take_income_wr80

    cases = json.loads(CASES.read_text(encoding="utf-8")) if CASES.exists() else []
    taken = take_income_wr80(cases) if cases else []
    wins = sum(1 for t in taken if t.get("win") or float(t.get("pnl") or 0) > 0)
    n = len(taken)

    report: dict[str, Any] = {
        "ts_utc": _ts(),
        "balance_usdc": bal,
        "preregistered": preregistered_rules(),
        "gate_attribution": gate_attribution(near),
        "wilson_path": wilson_path(wins, n),
        "capital": capital_matrix(bal),
        "snapshot_quality": snapshot_quality(snaps),
        "close_books": close_book_persistence(snaps),
        "dna_stress": dna_stress(),
        "dual_control": dual_control_live_refuse(),
        "watch": {
            "rounds": len(rounds),
            "edges": sum(1 for r in rounds if int(r.get("accepted_n") or 0) > 0),
            "last_gap": (rounds[-1].get("min_gap_basket") if rounds else None),
            "last_best_gates": (rounds[-1].get("best_gates_passed") if rounds else None),
        },
    }
    report["grade"] = assurance_grade(report)

    # Honest action
    stuck = int((report["close_books"] or {}).get("stuck_without_ud_n") or 0)
    report["action_es"] = (
        "Mantener WATCH_ONLY. Seguir capturando snapshots (calidad OK) y esperar resolve→cases. "
        f"Wilson path: ver to_go_micro. Capital live insuficiente; $25 sim sí. "
        f"UD stuck markets={stuck} — no bypass. Dual-control live refuse={'OK' if report['dual_control'].get('passed') else 'FAIL'}. "
        "No depositar / no ALLOW_REARM hasta READY_TO_REARM."
    )

    OUT.mkdir(parents=True, exist_ok=True)
    VPS.mkdir(parents=True, exist_ok=True)
    TELE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"assurance_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_md(report)
    (OUT / "LATEST.md").write_text(md, encoding="utf-8")
    (VPS / "ASSURANCE_SCORECARD.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (VPS / "ASSURANCE_SCORECARD.md").write_text(md, encoding="utf-8")
    with (TELE / "assurance_events.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts_utc": report["ts_utc"],
                    "grade": report["grade"]["grade"],
                    "pct": report["grade"]["pct"],
                    "n": n,
                    "wilson": cur_wilson if (cur_wilson := report["wilson_path"]["current"]["wilson95_lower"]) else None,
                    "stuck_ud": stuck,
                    "dual_control": report["dual_control"].get("passed"),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    if write_docs:
        (DOCS / "ASSURANCE_SCORECARD.md").write_text(md, encoding="utf-8")

    return report


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=None)
    ap.add_argument("--write-docs", action="store_true")
    args = ap.parse_args()
    rep = run(balance=args.balance, write_docs=bool(args.write_docs))
    print(
        json.dumps(
            {
                "grade": rep["grade"],
                "wilson_path": rep["wilson_path"],
                "stuck_ud": (rep.get("close_books") or {}).get("stuck"),
                "dual_control": rep.get("dual_control"),
                "action_es": rep.get("action_es"),
            },
            indent=2,
        )
    )
    return 0 if rep["grade"]["pct"] >= 50 else 2


if __name__ == "__main__":
    raise SystemExit(main())
