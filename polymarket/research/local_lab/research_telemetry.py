#!/usr/bin/env python3
"""
Forward research telemetry for Temperature Ladder (WATCH_ONLY).

Append-only journals + evidence progress toward rearm thresholds.
Never posts orders.

Journals under polymarket/data_local/local_lab/vps_runs/telemetry/:
  watch_rounds.jsonl
  near_miss.jsonl
  dna_hits.jsonl
  EVIDENCE_PROGRESS.json
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POLY = Path(__file__).resolve().parents[2]
TELE = POLY / "data_local" / "local_lab" / "vps_runs" / "telemetry"
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"

MIN_N_DEPOSIT = 30
MIN_N_GO = 50
MIN_WILSON = 0.80
DNA_BASKET = 0.50
DNA_LEG = 0.39
DNA_UD_RATIO = 0.65


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    TELE.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def _max_leg_from_block(block: dict[str, Any]) -> float | None:
    """Best available max leg ask from legs, skip string, or entries."""
    skip = str(block.get("skip") or "")
    m = re.search(r"max_leg=([0-9.]+)", skip)
    if m:
        return float(m.group(1))
    prices: list[float] = []
    for leg in block.get("legs") or []:
        p = leg.get("price")
        if isinstance(p, (int, float)):
            prices.append(float(p))
    if prices:
        return max(prices)
    for p in (block.get("entries") or {}).values():
        if isinstance(p, (int, float)):
            prices.append(float(p))
    # entries are full book — max of selected ladder legs preferred; if only entries,
    # use top-3 cheapest as proxy for press basket max leg
    if len(prices) >= 3:
        return max(sorted(prices)[:3])
    return max(prices) if prices else None


def gate_scoreboard(block: dict[str, Any]) -> dict[str, Any]:
    """DNA gates: basket≤0.50, max_leg≤0.39, underdispersion (ratio≤0.65). Never relax."""
    basket = block.get("basket_cost")
    basket_f = float(basket) if isinstance(basket, (int, float)) else None
    max_leg = _max_leg_from_block(block)
    ud = block.get("ud") if isinstance(block.get("ud"), dict) else {}
    ratio = ud.get("ratio")
    if ratio is None and block.get("underdispersed") is not None:
        # legacy rows without ratio: trust boolean only
        ud_ok = bool(block.get("underdispersed"))
        ratio_f = None
    else:
        ratio_f = float(ratio) if isinstance(ratio, (int, float)) else None
        ud_ok = bool(ud.get("underdispersed")) if ud else bool(block.get("underdispersed"))
        if ratio_f is not None:
            ud_ok = ratio_f <= DNA_UD_RATIO + 1e-12
    basket_ok = basket_f is not None and basket_f <= DNA_BASKET + 1e-12
    leg_ok = max_leg is not None and max_leg <= DNA_LEG + 1e-12
    waiting: list[str] = []
    if not basket_ok:
        waiting.append("basket")
    if not leg_ok:
        waiting.append("leg")
    if not ud_ok:
        waiting.append("ud")
    passed = int(basket_ok) + int(leg_ok) + int(ud_ok)
    return {
        "basket_ok": basket_ok,
        "leg_ok": leg_ok,
        "ud_ok": ud_ok,
        "gates_passed": passed,
        "gates_total": 3,
        "waiting": waiting,
        "basket": round(basket_f, 4) if basket_f is not None else None,
        "max_leg": round(max_leg, 4) if max_leg is not None else None,
        "ud_ratio": round(ratio_f, 4) if ratio_f is not None else None,
        "gap_basket": round(max(0.0, (basket_f or 0.0) - DNA_BASKET), 4) if basket_f is not None else None,
    }


def parse_near_miss_gaps(nm: dict[str, Any]) -> dict[str, Any]:
    """Extract gap-to-DNA metrics from skip string / fields."""
    skip = str(nm.get("skip") or "")
    basket = float(nm.get("basket_cost") or 0.0)
    gap_basket = round(max(0.0, basket - DNA_BASKET), 4)
    max_leg = _max_leg_from_block(nm)
    gap_leg = round(max(0.0, (max_leg or 0.0) - DNA_LEG), 4) if max_leg is not None else None
    reasons = []
    if basket > DNA_BASKET + 1e-12:
        reasons.append("basket_rich")
    if max_leg is not None and max_leg > DNA_LEG + 1e-12:
        reasons.append("max_leg")
    if "not_underdispersed" in skip or not bool(nm.get("underdispersed")):
        if "not_underdispersed" in skip or nm.get("underdispersed") is False:
            reasons.append("not_underdispersed")
    if "ev=" in skip and "<" in skip:
        reasons.append("ev_low")
    sb = gate_scoreboard(nm)
    return {
        "gap_basket": gap_basket,
        "max_leg": max_leg,
        "gap_leg": gap_leg,
        "reasons": reasons,
        "basket_ev": nm.get("basket_ev"),
        "gates": sb,
    }


def research_sample_stats() -> dict[str, Any]:
    """Historical DNA sample from cases (baseline). Forward hits added separately."""
    from polymarket.research.local_lab.assure_wr80_income import take_income_wr80

    if not CASES.exists():
        return {"n": 0, "wins": 0, "wr_point": 0.0, "wilson95_lower": 0.0, "source": "missing_cases"}
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    raw = take_income_wr80(cases)
    wins = sum(1 for t in raw if t.get("win") or float(t.get("pnl") or 0) > 0)
    n = len(raw)
    return {
        "n": n,
        "wins": wins,
        "wr_point": round(wins / n, 4) if n else 0.0,
        "wilson95_lower": round(_wilson_lower(wins, n), 4),
        "source": "cases_take_income_wr80",
    }


def forward_hit_count() -> dict[str, Any]:
    path = TELE / "dna_hits.jsonl"
    if not path.exists():
        return {"forward_hits_logged": 0, "forward_resolved": 0, "forward_wins": 0}
    hits = 0
    resolved = 0
    wins = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        hits += 1
        if row.get("resolved"):
            resolved += 1
            if row.get("win"):
                wins += 1
    return {
        "forward_hits_logged": hits,
        "forward_resolved": resolved,
        "forward_wins": wins,
    }


def write_forward_progress() -> dict[str, Any]:
    """How many live books we're tracking toward future DNA n."""
    path = TELE / "quote_snapshots.jsonl"
    rows: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    best: dict[str, dict[str, Any]] = {}
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        slug = str(r.get("slug") or "")
        if not slug or len(r.get("entries") or {}) < 3:
            continue
        latest[slug] = r
        cur = best.get(slug)
        if cur is None or float(r.get("basket_cost") or 99) < float(cur.get("basket_cost") or 99):
            best[slug] = dict(r)
    # Overlay latest UD diagnostics onto best-basket row
    for slug, row in best.items():
        lat = latest.get(slug) or {}
        if lat.get("ud") is not None:
            row["ud"] = lat.get("ud")
            row["underdispersed"] = lat.get("underdispersed")
            row["model_temps"] = lat.get("model_temps")
            row["typical_spread"] = lat.get("typical_spread")
    pending = []
    close = []
    two_of_three: list[dict[str, Any]] = []
    for slug, r in sorted(best.items(), key=lambda kv: float(kv[1].get("basket_cost") or 99)):
        # Prefer latest quote for live gates; keep best basket as reference
        live = latest.get(slug) or r
        gates_live = gate_scoreboard(live)
        gates_best = gate_scoreboard(r)
        item = {
            "slug": slug,
            "city": r.get("city"),
            "day": r.get("day"),
            "best_basket": r.get("basket_cost"),
            "gap": round(max(0.0, float(r.get("basket_cost") or 0) - DNA_BASKET), 4),
            "live_basket": live.get("basket_cost"),
            "entries_n": len(r.get("entries") or {}),
            "dna_take_seen": bool(r.get("dna_take")),
            "underdispersed": live.get("underdispersed", r.get("underdispersed")),
            "ud": live.get("ud") or r.get("ud"),
            "gates_live": gates_live,
            "gates_at_best_basket": gates_best,
        }
        pending.append(item)
        if item["gap"] <= 0.12:
            close.append(item)
        if int(gates_live.get("gates_passed") or 0) >= 2:
            two_of_three.append(item)
    two_of_three.sort(
        key=lambda x: (
            -int((x.get("gates_live") or {}).get("gates_passed") or 0),
            float((x.get("gates_live") or {}).get("gap_basket") or 99),
        )
    )
    hist = research_sample_stats()
    out = {
        "ts_utc": _ts(),
        "snapshots_total": len(rows),
        "markets_tracked": len(best),
        "close_to_dna_gap_le_12c": close,
        "gates_2_of_3": two_of_three,
        "pending_resolve": pending,
        "historical_n": hist.get("n"),
        "historical_wilson": hist.get("wilson95_lower"),
        "n_to_go_micro": max(0, MIN_N_GO - int(hist.get("n") or 0)),
        "note_es": (
            "Cada mercado tracked con snapshot se puede convertir en case DNA al resolver. "
            "Esa es la vía para subir n (CLOB history no cubre pre-julio). "
            "Scoreboard gates DNA: basket≤0.50 · leg≤0.39 · UD ratio≤0.65 (sin aflojar)."
        ),
    }
    TELE.mkdir(parents=True, exist_ok=True)
    (TELE / "FORWARD_PROGRESS.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (TELE / "GATE_SCOREBOARD.json").write_text(
        json.dumps(
            {
                "ts_utc": out["ts_utc"],
                "gates_2_of_3": two_of_three,
                "all": [
                    {
                        "city": p.get("city"),
                        "day": p.get("day"),
                        "slug": p.get("slug"),
                        **(p.get("gates_live") or {}),
                    }
                    for p in pending
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    vps = POLY / "data_local" / "local_lab" / "vps_runs"
    vps.mkdir(parents=True, exist_ok=True)
    (vps / "FORWARD_PROGRESS.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (vps / "GATE_SCOREBOARD.json").write_text(
        (TELE / "GATE_SCOREBOARD.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    lines = [
        "# Forward progress",
        "",
        f"- tracked markets: **{len(best)}** (snapshots {len(rows)})",
        f"- historical DNA n: **{hist.get('n')}** · Wilson {hist.get('wilson95_lower')}",
        f"- faltan a GO_MICRO: **{max(0, MIN_N_GO - int(hist.get('n') or 0))}**",
        "",
        "## Gate scoreboard (2/3+)",
    ]
    for c in two_of_three:
        g = c.get("gates_live") or {}
        lines.append(
            f"- {g.get('gates_passed')}/3 {c['city']} {c['day']}: "
            f"basket={g.get('basket')} leg={g.get('max_leg')} ud_ratio={g.get('ud_ratio')} "
            f"waiting={','.join(g.get('waiting') or []) or 'none'}"
        )
    if not two_of_three:
        lines.append("- (ninguno con 2/3 ahora)")
    lines.extend(["", "## Close to DNA (gap ≤ 12¢)"])
    for c in close:
        ud = c.get("ud") or {}
        g = c.get("gates_live") or {}
        lines.append(
            f"- {c['city']} {c['day']}: basket {c['best_basket']} (gap {c['gap']}) "
            f"gates={g.get('gates_passed')}/3 UD={c.get('underdispersed')} "
            f"ratio={ud.get('ratio')} spread={ud.get('spread')}/{ud.get('typical')}"
        )
    if not close:
        lines.append("- (ninguno ahora)")
    lines.extend(["", "## All tracked", ""])
    for p in pending:
        g = p.get("gates_live") or {}
        lines.append(
            f"- {g.get('gates_passed')}/3 {p['city']} {p['day']}: "
            f"{p['best_basket']} gap={p['gap']} wait={','.join(g.get('waiting') or [])}"
        )
    md = "\n".join(lines) + "\n"
    (vps / "FORWARD_PROGRESS.md").write_text(md, encoding="utf-8")
    (TELE / "FORWARD_PROGRESS.md").write_text(md, encoding="utf-8")
    return out


def write_evidence_progress() -> dict[str, Any]:
    hist = research_sample_stats()
    fwd = forward_hit_count()
    # Evidence for rearm still dominated by historical until forward resolves;
    # show both so operator sees progress.
    n = hist["n"]
    progress = {
        "ts_utc": _ts(),
        "historical": hist,
        "forward": fwd,
        "thresholds": {
            "min_n_deposit_talk": MIN_N_DEPOSIT,
            "min_n_go_micro": MIN_N_GO,
            "min_wilson95": MIN_WILSON,
        },
        "n_to_deposit_talk": max(0, MIN_N_DEPOSIT - n),
        "n_to_go_micro": max(0, MIN_N_GO - n),
        "wilson_ok": hist["wilson95_lower"] + 1e-12 >= MIN_WILSON,
        "note_es": (
            "n histórico=11 es débil. Los dna_hits forward se acumulan en telemetría; "
            "solo cuentan para WR cuando estén resolved. No depositar por MC."
        ),
    }
    TELE.mkdir(parents=True, exist_ok=True)
    (TELE / "EVIDENCE_PROGRESS.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
    # also mirror for status readers
    vps = POLY / "data_local" / "local_lab" / "vps_runs"
    vps.mkdir(parents=True, exist_ok=True)
    (vps / "EVIDENCE_PROGRESS.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
    try:
        progress["forward_progress"] = write_forward_progress()
    except Exception as exc:
        progress["forward_progress_error"] = f"{type(exc).__name__}: {exc}"
    return progress


def log_watch_round(row: dict[str, Any], stack: dict[str, Any] | None = None) -> None:
    """Persist slim round + near-miss gaps; DNA hits if any; quote snapshots."""
    market = ((stack or {}).get("market_now") or {}) if stack else {}
    gate_rows: list[dict[str, Any]] = []
    best_gates = 0
    best_gate_slug = None
    for block in (market.get("accepted") or []) + (market.get("near_miss") or []) + (market.get("skipped") or []):
        sb = gate_scoreboard(block)
        gate_rows.append(
            {
                "slug": block.get("slug"),
                "city": block.get("city"),
                "day": block.get("day"),
                **sb,
            }
        )
        if int(sb.get("gates_passed") or 0) > best_gates:
            best_gates = int(sb["gates_passed"])
            best_gate_slug = block.get("slug")

    slim = {
        "ts_utc": row.get("ts_utc") or _ts(),
        "round": row.get("round"),
        "mode": row.get("mode"),
        "balance_pusd": row.get("balance_pusd"),
        "accepted_n": row.get("accepted_n"),
        "near_miss_n": row.get("near_miss_n"),
        "geoblock_ok": row.get("geoblock_ok"),
        "ready_to_arm": row.get("ready_to_arm"),
        "blockers": row.get("blockers"),
        "accepted_slugs": row.get("accepted_slugs"),
        "min_gap_basket": row.get("min_gap_basket"),
        "interval_next_s": row.get("interval_next_s"),
        "recheck": row.get("recheck"),
        "recheck_pass": row.get("recheck_pass"),
        "best_gates_passed": best_gates,
        "best_gates_slug": best_gate_slug,
        "gates_2_of_3_n": sum(1 for g in gate_rows if int(g.get("gates_passed") or 0) >= 2),
    }
    _append_jsonl(TELE / "watch_rounds.jsonl", slim)

    for nm in market.get("near_miss") or []:
        gaps = parse_near_miss_gaps(nm)
        _append_jsonl(
            TELE / "near_miss.jsonl",
            {
                "ts_utc": slim["ts_utc"],
                "round": slim["round"],
                "slug": nm.get("slug"),
                "city": nm.get("city"),
                "day": nm.get("day"),
                "basket_cost": nm.get("basket_cost"),
                "skip": nm.get("skip"),
                "tier": nm.get("tier"),
                **gaps,
                "ud": nm.get("ud"),
                "underdispersed": nm.get("underdispersed"),
                "policy": "REJECT_DNA",
            },
        )

    for c in market.get("accepted") or []:
        _append_jsonl(
            TELE / "dna_hits.jsonl",
            {
                "ts_utc": slim["ts_utc"],
                "round": slim["round"],
                "slug": c.get("slug"),
                "city": c.get("city"),
                "day": c.get("day"),
                "basket_cost": c.get("basket_cost"),
                "basket_ev": c.get("basket_ev"),
                "notional_usdc": c.get("notional_usdc"),
                "underdispersed": c.get("underdispersed"),
                "legs": c.get("legs"),
                "gates": gate_scoreboard(c),
                "resolved": False,
                "win": None,
                "pnl": None,
                "source": "watch_only_forward",
            },
        )

    # Forward quote snapshots (asks we saw) → future cases after resolve
    seen_slugs: set[str] = set()
    for block in (market.get("accepted") or []) + (market.get("near_miss") or []) + (market.get("skipped") or []):
        slug = block.get("slug")
        if not slug or slug in seen_slugs:
            continue
        entries = block.get("entries") or {}
        if not entries and block.get("legs"):
            entries = {
                str(x.get("name")): float(x["price"])
                for x in block.get("legs") or []
                if x.get("name") is not None and x.get("price") is not None
            }
        if len(entries) < 3:
            continue
        seen_slugs.add(str(slug))
        sb = gate_scoreboard(block)
        _append_jsonl(
            TELE / "quote_snapshots.jsonl",
            {
                "ts_utc": slim["ts_utc"],
                "round": slim["round"],
                "slug": slug,
                "city": block.get("city"),
                "day": block.get("day"),
                "basket_cost": block.get("basket_cost"),
                "basket_ev": block.get("basket_ev"),
                "underdispersed": block.get("underdispersed"),
                "models": block.get("models"),
                "entries": entries,
                "legs": block.get("legs"),
                "dna_take": bool(block.get("dna_take") or block.get("accepted")),
                "ud": block.get("ud"),
                "model_temps": block.get("model_temps"),
                "typical_spread": block.get("typical_spread"),
                "skip": block.get("skip"),
                "gates": sb,
                "max_leg": sb.get("max_leg"),
                "source": "watch_live",
            },
        )

    write_evidence_progress()
    return slim


def digest_last_hours(hours: float = 24.0) -> dict[str, Any]:
    """Aggregate telemetry for daily digest."""
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600

    def _load(name: str) -> list[dict[str, Any]]:
        p = TELE / name
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            ts = row.get("ts_utc") or ""
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if t >= cutoff:
                out.append(row)
        return out

    rounds = _load("watch_rounds.jsonl")
    misses = _load("near_miss.jsonl")
    hits = _load("dna_hits.jsonl")
    reasons: dict[str, int] = {}
    for m in misses:
        for r in m.get("reasons") or ["unknown"]:
            reasons[r] = reasons.get(r, 0) + 1
    gaps = [float(m.get("gap_basket") or 0) for m in misses]
    ev = write_evidence_progress()
    return {
        "ts_utc": _ts(),
        "window_hours": hours,
        "rounds": len(rounds),
        "rounds_with_edge": sum(1 for r in rounds if int(r.get("accepted_n") or 0) > 0),
        "dna_hits_logged": len(hits),
        "near_miss_events": len(misses),
        "near_miss_reasons": reasons,
        "gap_basket_avg": round(sum(gaps) / len(gaps), 4) if gaps else None,
        "gap_basket_min": round(min(gaps), 4) if gaps else None,
        "evidence": ev,
    }


if __name__ == "__main__":
    print(json.dumps(write_evidence_progress(), indent=2))
