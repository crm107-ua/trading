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


def parse_near_miss_gaps(nm: dict[str, Any]) -> dict[str, Any]:
    """Extract gap-to-DNA metrics from skip string / fields."""
    skip = str(nm.get("skip") or "")
    basket = float(nm.get("basket_cost") or 0.0)
    gap_basket = round(max(0.0, basket - 0.50), 4)
    max_leg = None
    m = re.search(r"max_leg=([0-9.]+)", skip)
    if m:
        max_leg = float(m.group(1))
    gap_leg = round(max(0.0, (max_leg or 0.0) - 0.39), 4) if max_leg is not None else None
    reasons = []
    if basket > 0.50 + 1e-12:
        reasons.append("basket_rich")
    if max_leg is not None and max_leg > 0.39 + 1e-12:
        reasons.append("max_leg")
    if "not_underdispersed" in skip:
        reasons.append("not_underdispersed")
    if "ev=" in skip and "<" in skip:
        reasons.append("ev_low")
    return {
        "gap_basket": gap_basket,
        "max_leg": max_leg,
        "gap_leg": gap_leg,
        "reasons": reasons,
        "basket_ev": nm.get("basket_ev"),
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
    return progress


def log_watch_round(row: dict[str, Any], stack: dict[str, Any] | None = None) -> None:
    """Persist slim round + near-miss gaps; DNA hits if any; quote snapshots."""
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
    }
    _append_jsonl(TELE / "watch_rounds.jsonl", slim)

    market = ((stack or {}).get("market_now") or {}) if stack else {}
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
                "skip": block.get("skip"),
                "source": "watch_live",
            },
        )

    write_evidence_progress()


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
