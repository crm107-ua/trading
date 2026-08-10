#!/usr/bin/env python3
"""Ranked improvement candidates from forward research telemetry (WATCH_ONLY).

Reads (default):
  polymarket/data_local/local_lab/vps_runs/telemetry/
    watch_rounds.jsonl
    near_miss.jsonl
    dna_hits.jsonl

Writes:
  IMPROVEMENT_CANDIDATES.json
  LATEST_SCAN.txt
  (same folder + mirror under vps_runs/)

Does NOT change DNA gates or place orders.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# scripts/ → polymarket/
POLY = Path(__file__).resolve().parents[1]
TELE = POLY / "data_local" / "local_lab" / "vps_runs" / "telemetry"
VPS = POLY / "data_local" / "local_lab" / "vps_runs"


def _load_jsonl(path: Path, limit: int = 5000) -> list[dict[str, Any]]:
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


def scan(tele_dir: Path) -> dict[str, Any]:
    rounds = _load_jsonl(tele_dir / "watch_rounds.jsonl")
    near = _load_jsonl(tele_dir / "near_miss.jsonl")
    hits = _load_jsonl(tele_dir / "dna_hits.jsonl")

    city_near: Counter[str] = Counter()
    city_edge: Counter[str] = Counter()
    basket_near: list[float] = []
    leg_near: list[float] = []
    gap_basket: list[float] = []
    reasons: Counter[str] = Counter()
    hour_near: Counter[int] = Counter()
    hour_edge: Counter[int] = Counter()
    rounds_with_edge = 0

    for r in rounds:
        if int(r.get("accepted_n") or 0) > 0:
            rounds_with_edge += 1
        try:
            hour = datetime.fromisoformat(str(r.get("ts_utc", "")).replace("Z", "+00:00")).hour
        except Exception:
            hour = None
        if int(r.get("near_miss_n") or 0) > 0 and hour is not None:
            hour_near[hour] += 1
        if int(r.get("accepted_n") or 0) > 0 and hour is not None:
            hour_edge[hour] += 1

    for n in near:
        city = str(n.get("city") or "?")
        city_near[city] += 1
        b = n.get("basket_cost")
        if isinstance(b, (int, float)):
            basket_near.append(float(b))
        g = n.get("gap_basket")
        if isinstance(g, (int, float)):
            gap_basket.append(float(g))
        elif isinstance(b, (int, float)):
            gap_basket.append(max(0.0, float(b) - 0.50))
        leg = n.get("max_leg")
        if isinstance(leg, (int, float)):
            leg_near.append(float(leg))
        for reason in n.get("reasons") or []:
            reasons[str(reason)] += 1

    for h in hits:
        city_edge[str(h.get("city") or "?")] += 1

    candidates: list[dict[str, Any]] = []

    if gap_basket:
        med_gap = statistics.median(gap_basket)
        p_close = sum(1 for g in gap_basket if g <= 0.05) / len(gap_basket)
        p_mid = sum(1 for g in gap_basket if 0.05 < g <= 0.20) / len(gap_basket)
        candidates.append(
            {
                "id": "basket_near_cluster",
                "priority": "HIGH" if p_close >= 0.35 else ("MED" if p_mid >= 0.4 else "LOW"),
                "title": "Cluster near-miss por basket sobre DNA 0.50",
                "evidence": {
                    "n_near": len(gap_basket),
                    "median_gap_over_050": round(med_gap, 4),
                    "pct_within_5c": round(p_close, 3),
                    "pct_5c_to_20c": round(p_mid, 3),
                    "median_basket": round(statistics.median(basket_near), 4) if basket_near else None,
                    "near_by_city": dict(city_near.most_common(6)),
                },
                "action": (
                    "NO bajar DNA a 0.55. Mejoras ops: (a) recheck +30s/+90s en la misma ventana, "
                    "(b) telemetría de si el basket cae a ≤0.50 sin tocar umbral."
                ),
                "dna_impact": "none",
            }
        )

    if reasons:
        candidates.append(
            {
                "id": "dominant_reject_reasons",
                "priority": "MED",
                "title": "Razones de rechazo dominantes",
                "evidence": {"top_reasons": reasons.most_common(6)},
                "action": "Priorizar telemetría (leg vs underdispersion vs liquidez) según razón #1.",
                "dna_impact": "none",
            }
        )

    if hour_near or hour_edge:
        candidates.append(
            {
                "id": "hour_of_day_focus",
                "priority": "MED",
                "title": "Concentrar vigilancia en horas calientes",
                "evidence": {
                    "near_hours_utc": hour_near.most_common(5),
                    "edge_hours_utc": hour_edge.most_common(5),
                },
                "action": "Acortar interval en horas calientes; alargar en muertas (misma DNA).",
                "dna_impact": "none",
            }
        )

    n_edge = len(hits) or rounds_with_edge
    n_rounds = len(rounds)
    candidates.append(
        {
            "id": "sample_growth_discipline",
            "priority": "CRITICAL",
            "title": "Disciplina de muestra hacia n≥50 antes de rearme",
            "evidence": {
                "watch_rounds_logged": n_rounds,
                "edges_logged": n_edge,
                "near_miss_logged": len(near),
                "rearm_requires": {"min_n": 50, "wilson_lcb": 0.80},
            },
            "action": "Mantener WATCH_ONLY x3 bankrolls; cada EDGE DNA forward suma evidencia. No depositar por sim.",
            "dna_impact": "none",
        }
    )

    if n_rounds < 30:
        candidates.append(
            {
                "id": "bootstrap_telemetry",
                "priority": "HIGH",
                "title": "Fase bootstrap de telemetría",
                "evidence": {"rounds": n_rounds},
                "action": "Dejar correr los 3 procesos ≥24–48h antes de tocar ops; no cambiar umbrales DNA.",
                "dna_impact": "none",
            }
        )

    # UD stuck: close basket but underdispersion never OK (protective gate)
    ud_fail = 0
    ud_total = 0
    for n in near:
        g = n.get("gates") or {}
        waiting = set(g.get("waiting") or [])
        if "ud" in waiting or "not_underdispersed" in (n.get("reasons") or []):
            ud_fail += 1
        if g or n.get("reasons"):
            ud_total += 1
    if ud_fail >= 20:
        candidates.append(
            {
                "id": "ud_gate_protective_stuck",
                "priority": "HIGH",
                "title": "Underdispersion bloquea libros cercanos (gate protector)",
                "evidence": {
                    "ud_waiting_or_reject_events": ud_fail,
                    "near_with_gate_info": ud_total,
                    "hint": "HK suele tener ratio~2.5 vs umbral 0.65",
                },
                "action": (
                    "NO quitar require_underdispersion. Seguir scoreboard + assurance_research; "
                    "solo EDGE cuando UD converja de verdad."
                ),
                "dna_impact": "none",
            }
        )

    # Capital readiness reminder from live balance in latest round
    last_bal = None
    for r in reversed(rounds):
        if r.get("balance_pusd") is not None:
            last_bal = float(r["balance_pusd"])
            break
    if last_bal is not None and last_bal < 25:
        candidates.append(
            {
                "id": "capital_below_deposit_floor",
                "priority": "HIGH",
                "title": f"Saldo live ${last_bal:.2f} < floor depósito $25",
                "evidence": {"balance_pusd": last_bal},
                "action": "Seguir what-if USD100/USD200; no depositar hasta rearm_income_gate=READY_TO_REARM.",
                "dna_impact": "none",
            }
        )

    order = {"CRITICAL": 0, "HIGH": 1, "MED": 2, "LOW": 3}
    candidates.sort(key=lambda c: order.get(str(c.get("priority")), 9))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tele_dir": str(tele_dir),
        "summary": {
            "rounds": n_rounds,
            "rounds_with_edge": rounds_with_edge,
            "near_miss_events": len(near),
            "dna_hits": len(hits),
            "near_by_city": dict(city_near),
            "edge_by_city": dict(city_edge),
            "median_near_basket": round(statistics.median(basket_near), 4) if basket_near else None,
            "median_near_worst_leg": round(statistics.median(leg_near), 4) if leg_near else None,
            "median_gap_basket": round(statistics.median(gap_basket), 4) if gap_basket else None,
            "last_balance_pusd": last_bal,
        },
        "candidates": candidates,
        "posture": "RESEARCH_ONLY + WATCH_ONLY — mejoras = observabilidad/ops, no relajar DNA",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tele-dir", default=str(TELE))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    tele = Path(args.tele_dir)
    tele.mkdir(parents=True, exist_ok=True)
    out = scan(tele)
    payload = json.dumps(out, indent=2) + "\n"
    (tele / "IMPROVEMENT_CANDIDATES.json").write_text(payload, encoding="utf-8")
    VPS.mkdir(parents=True, exist_ok=True)
    (VPS / "IMPROVEMENT_CANDIDATES.json").write_text(payload, encoding="utf-8")
    lines = [
        f"scan={out['generated_at']}",
        (
            f"rounds={out['summary']['rounds']} edges={out['summary']['rounds_with_edge']} "
            f"near={out['summary']['near_miss_events']} dna_hits={out['summary']['dna_hits']}"
        ),
        f"median_gap_basket={out['summary'].get('median_gap_basket')} bal={out['summary'].get('last_balance_pusd')}",
        f"posture={out['posture']}",
        "",
        "CANDIDATES:",
    ]
    for c in out["candidates"]:
        lines.append(f"- [{c['priority']}] {c['id']}: {c['title']}")
        lines.append(f"  action: {c['action']}")
    text = "\n".join(lines) + "\n"
    (tele / "LATEST_SCAN.txt").write_text(text, encoding="utf-8")
    (VPS / "LATEST_SCAN.txt").write_text(text, encoding="utf-8")
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
