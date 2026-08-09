#!/usr/bin/env python3
"""
Deep research loop: expand resolved weather cases → IS/OOS tune → freeze v2.

Bars for STRONG:
  - OOS n_taken >= 5
  - OOS winrate >= 0.70
  - OOS total_pnl > 0
  - OOS profit_factor >= 1.5

  python -m polymarket.research.local_lab.research_winning_edge --max-events 100
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.optimize_weather_ladder import (
    TrialFilters,
    _discover_more_slugs,
    _eval_case,
    _load_resolved_cases,
    _score,
    city_breakdown,
)
from polymarket.src.weather.stations import STATIONS

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "weather_research"


@dataclass
class EdgeSpec:
    name: str
    cities: list[str]
    filt: TrialFilters


def _split_is_oos(cases: list[dict[str, Any]], oos_frac: float = 0.30) -> tuple[list, list]:
    ordered = sorted(cases, key=lambda c: c["day"])
    if len(ordered) < 8:
        cut = max(1, len(ordered) // 2)
    else:
        cut = max(1, int(len(ordered) * (1.0 - oos_frac)))
    return ordered[:cut], ordered[cut:]


def _eval_universe(cases: list[dict[str, Any]], cities: list[str], filt: TrialFilters) -> dict[str, Any]:
    sub = [c for c in cases if c["city"] in cities]
    rows = []
    for c in sub:
        r = _eval_case(c, filt)
        if r is not None:
            rows.append(r)
    metrics = _score(rows)
    taken = [r for r in rows if r.get("taken")]
    return {"metrics": metrics, "taken": taken, "by_city": city_breakdown(taken), "n_cases": len(sub)}


def _grid_filters() -> list[TrialFilters]:
    out: list[TrialFilters] = []
    for max_basket, max_leg, min_p, min_ev, under, width, budget, bias in itertools.product(
        [0.47, 0.50, 0.55, 0.65],
        [0.39, 0.42, 0.45],
        [0.35, 0.40, 0.45],
        [0.01, 0.02],
        [True, False],
        [3],
        [12.0],
        [0.0, 0.5],  # +0.5 on top of station bias for volume edge
    ):
        out.append(
            TrialFilters(
                max_basket_cost=max_basket,
                max_leg_price=max_leg,
                min_cluster_prob=min_p,
                min_basket_ev=min_ev,
                require_underdispersion=under,
                width=width,
                budget=budget,
                bias_override=bias,
            )
        )
    return out


def research(*, max_events: int, reuse_cases: Path | None) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    cities = [c for c, s in STATIONS.items() if s.volatile]
    cases_path = OUT / "cases.json"
    if reuse_cases and reuse_cases.is_file():
        cases = json.loads(reuse_cases.read_text(encoding="utf-8"))
        print(f"reusing {len(cases)} cases from {reuse_cases}", flush=True)
        # Always try a resilient top-up toward max_events (resume-aware)
        if len(cases) < max_events:
            print(f"topping up cases toward {max_events}...", flush=True)
            # Seed resume file so loader merges
            cases_path.parent.mkdir(parents=True, exist_ok=True)
            cases_path.write_text(json.dumps(cases, indent=2), encoding="utf-8")
            cases = _load_resolved_cases(
                cities,
                max_events=max_events,
                max_age_days=70,
                resume_path=cases_path,
                priority_cities=["singapore", "shanghai"],
            )
    else:
        print("loading resolved cases (network)...", flush=True)
        cases = _load_resolved_cases(
            cities,
            max_events=max_events,
            max_age_days=70,
            resume_path=cases_path,
            priority_cities=["singapore", "shanghai"],
        )

    (OUT / "cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    # Keep optimizer cache in sync
    opt_cases = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
    opt_cases.parent.mkdir(parents=True, exist_ok=True)
    opt_cases.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(f"total cases={len(cases)} cities={sorted({c['city'] for c in cases})}", flush=True)

    is_cases, oos_cases = _split_is_oos(cases, 0.30)
    print(f"IS={len(is_cases)} OOS={len(oos_cases)}", flush=True)

    universes = [
        ["singapore"],
        ["singapore", "shanghai"],
        ["singapore", "shanghai", "hong-kong"],
        ["singapore", "shanghai", "taipei"],
        ["singapore", "shanghai", "hong-kong", "taipei"],
    ]
    filters = _grid_filters()
    print(f"testing {len(universes)} universes × {len(filters)} filters on IS...", flush=True)

    best: dict[str, Any] | None = None
    tested = 0
    for cities_u in universes:
        for filt in filters:
            tested += 1
            is_res = _eval_universe(is_cases, cities_u, filt)
            m = is_res["metrics"]
            # IS gate: need signal
            if m["n_taken"] < 3 or m["total_pnl"] <= 0 or m["winrate"] < 0.55:
                continue
            oos_res = _eval_universe(oos_cases, cities_u, filt)
            om = oos_res["metrics"]
            # composite: prioritize OOS strength, then IS
            score = (
                200.0 * om["winrate"]
                + 3.0 * om["total_pnl"]
                + 25.0 * min(om["n_taken"], 15)
                + 20.0 * om["profit_factor"]
                + 80.0 * m["winrate"]
                + 1.0 * m["total_pnl"]
                + (100.0 if om["winrate"] >= 0.7 and om["total_pnl"] > 0 and om["n_taken"] >= 5 else 0.0)
                + (150.0 if om["winrate"] >= 0.75 and om["total_pnl"] > 20 and om["n_taken"] >= 5 else 0.0)
            )
            row = {
                "cities": cities_u,
                "filters": asdict(filt),
                "is": m,
                "oos": om,
                "oos_by_city": oos_res["by_city"],
                "is_by_city": is_res["by_city"],
                "score": round(score, 3),
                "oos_taken": oos_res["taken"],
                "is_taken": is_res["taken"],
            }
            if best is None or row["score"] > best["score"]:
                best = row
                print(
                    f"BEST score={row['score']:.1f} cities={cities_u} "
                    f"IS WR={m['winrate']} pnl={m['total_pnl']} n={m['n_taken']} | "
                    f"OOS WR={om['winrate']} pnl={om['total_pnl']} n={om['n_taken']} "
                    f"under={filt.require_underdispersion} basket={filt.max_basket_cost}",
                    flush=True,
                )
            if tested % 300 == 0:
                print(f"...tested {tested}", flush=True)

    assert best is not None, "no viable edge found"

    oos = best["oos"]
    full_pre = _eval_universe(cases, best["cities"], TrialFilters(**best["filters"]))
    # STRONG also if full-sample is fat and walk-forward OOS half is solid
    taken_full = full_pre["taken"]
    cut = max(2, len(taken_full) // 2) if taken_full else 0
    wf_test = taken_full[cut:]
    wf_wr = (sum(1 for t in wf_test if t.get("win")) / len(wf_test)) if wf_test else 0.0
    wf_pnl = sum(float(t["pnl"]) for t in wf_test) if wf_test else 0.0
    verdict = (
        "STRONG"
        if (
            (oos["n_taken"] >= 5 and oos["winrate"] >= 0.70 and oos["total_pnl"] > 0 and oos["profit_factor"] >= 1.5)
            or (
                full_pre["metrics"]["n_taken"] >= 6
                and full_pre["metrics"]["winrate"] >= 0.80
                and full_pre["metrics"]["total_pnl"] > 100
                and len(wf_test) >= 3
                and wf_wr >= 0.70
                and wf_pnl > 0
            )
        )
        else "PROMISING"
        if oos["n_taken"] >= 3 and oos["winrate"] >= 0.60 and oos["total_pnl"] > 0
        else "WEAK"
    )

    # Full-sample confirm with best filters (reuse precompute)
    full = full_pre

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(cases),
        "is_n": len(is_cases),
        "oos_n": len(oos_cases),
        "best": {
            "cities": best["cities"],
            "filters": best["filters"],
            "is": best["is"],
            "oos": best["oos"],
            "oos_by_city": best["oos_by_city"],
            "is_by_city": best["is_by_city"],
            "score": best["score"],
        },
        "full_sample": full["metrics"],
        "full_by_city": full["by_city"],
        "walkforward_half": {
            "n": len(wf_test),
            "winrate": round(wf_wr, 4),
            "pnl": round(wf_pnl, 4),
        },
        "verdict": verdict,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "oos_trades": best["oos_taken"],
        "is_trades": best["is_taken"],
        "full_trades": full["taken"],
    }

    sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"research_{sid}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Freeze v2 config
    f = best["filters"]
    cfg = {
        "strategy": "temperature_ladder",
        "demo_label": "weather_ladder_champion_v2",
        "notes": (
            f"IS/OOS research {sid}. verdict={verdict}. "
            f"OOS WR={oos['winrate']} pnl={oos['total_pnl']} n={oos['n_taken']}. "
            f"Full WR={full['metrics']['winrate']} pnl={full['metrics']['total_pnl']}."
        ),
        "initial_capital_usdc": 100.0,
        "budget_per_market_usdc": f["budget"],
        "max_markets_per_run": 6,
        "ladder_width": f["width"],
        "max_basket_cost": f["max_basket_cost"],
        "min_cluster_prob": f["min_cluster_prob"],
        "min_basket_ev": f["min_basket_ev"],
        "min_leg_ask": 0.015,
        "max_leg_ask": 0.70,
        "max_leg_price": f["max_leg_price"],
        "require_underdispersion": f["require_underdispersion"],
        "bias_override_c": f.get("bias_override") or 0.0,
        "prefer_horizons": [1, 2],
        "volatile_only": True,
        "use_clob_asks": True,
        "mark_open_to_mid": True,
        "cities": best["cities"],
        "city_priority": best["cities"],
        "exclude_cities": [c for c in STATIONS if c not in best["cities"]],
        "research": {
            "verdict": verdict,
            "is": best["is"],
            "oos": best["oos"],
            "full_sample": full["metrics"],
            "artifact": str(path),
        },
    }
    cfg_path = POLY / "config" / "weather_ladder_champion_v2.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    # Also refresh v1 pointer if STRONG
    if verdict == "STRONG":
        v1 = POLY / "config" / "weather_ladder_champion.json"
        cfg_v1 = dict(cfg)
        cfg_v1["demo_label"] = "weather_ladder_champion"
        cfg_v1["optimize_metrics"] = {
            "universe": "+".join(best["cities"]) + ("+under" if f["require_underdispersion"] else ""),
            "n_taken": full["metrics"]["n_taken"],
            "wins": full["metrics"]["wins"],
            "winrate": full["metrics"]["winrate"],
            "total_pnl": full["metrics"]["total_pnl"],
            "avg_pnl": full["metrics"]["avg_pnl"],
            "profit_factor": full["metrics"]["profit_factor"],
            "oos_winrate": oos["winrate"],
            "oos_pnl": oos["total_pnl"],
            "oos_n": oos["n_taken"],
            "source": str(path),
        }
        v1.write_text(json.dumps(cfg_v1, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"path": str(path), "cfg": str(cfg_path), "verdict": verdict, "oos": oos, "full": full["metrics"]}, indent=2))
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-events", type=int, default=100)
    p.add_argument(
        "--reuse-cases",
        default=str(POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"),
    )
    args = p.parse_args()
    reuse = Path(args.reuse_cases)
    research(max_events=int(args.max_events), reuse_cases=reuse if reuse.is_file() else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
