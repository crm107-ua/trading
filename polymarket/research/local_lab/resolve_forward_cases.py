#!/usr/bin/env python3
"""
Resolve forward quote snapshots into DNA cases when markets close.

Live WATCH writes telemetry/quote_snapshots.jsonl (asks we actually saw).
This job turns resolved snapshots into weather_optimize/cases.json rows and
re-scores DNA takes — the only scalable evidence path (CLOB history is gone
for pre-July markets).

  python3 -m polymarket.research.local_lab.resolve_forward_cases
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.research_telemetry import write_evidence_progress
from polymarket.src.weather.markets import fetch_temp_event, winning_bucket

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
TELE = POLY / "data_local" / "local_lab" / "vps_runs" / "telemetry"
OUT = POLY / "data_local" / "local_lab" / "vps_runs"
SNAP = TELE / "quote_snapshots.jsonl"


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def _load_snaps() -> list[dict[str, Any]]:
    if not SNAP.exists():
        return []
    rows = []
    for line in SNAP.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _best_snap_per_slug(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Prefer DNA-pass snapshots; else cheapest basket with ≥3 entry legs."""
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        slug = r.get("slug")
        if not slug:
            continue
        entries = r.get("entries") or {}
        if len(entries) < 3:
            continue
        cur = best.get(slug)
        if cur is None:
            best[slug] = r
            continue
        # Prefer taken/DNA, then lower basket
        score = (1 if r.get("dna_take") else 0, -float(r.get("basket_cost") or 99))
        score_cur = (1 if cur.get("dna_take") else 0, -float(cur.get("basket_cost") or 99))
        if score > score_cur:
            best[slug] = r
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cases = json.loads(CASES.read_text(encoding="utf-8")) if CASES.exists() else []
    have = {c["slug"] for c in cases}
    before_takes = take_income_wr80(cases)
    before_n = len(before_takes)

    snaps = _best_snap_per_slug(_load_snaps())
    added = 0
    resolved_checked = 0
    for slug, snap in sorted(snaps.items()):
        if slug in have:
            continue
        try:
            ev = fetch_temp_event(slug, use_clob=False)
        except Exception as exc:
            print(f"fetch_fail {slug}: {exc}", flush=True)
            continue
        if ev is None or not ev.closed:
            continue
        resolved_checked += 1
        winner = winning_bucket(ev)
        if winner is None:
            continue
        entries = {str(k): float(v) for k, v in (snap.get("entries") or {}).items() if v is not None}
        if len(entries) < 3:
            continue
        models = snap.get("models") or {}
        if len(models) < 2:
            continue
        point_temps = sorted({b.temp_c for b in ev.buckets if b.temp_c is not None})
        case = {
            "slug": slug,
            "city": snap.get("city") or ev.city,
            "day": snap.get("day") or ev.day.isoformat(),
            "winner": winner.name,
            "winner_temp": winner.temp_c,
            "winner_open_high": "or higher" in (winner.name or "").lower(),
            "winner_open_low": "or below" in (winner.name or "").lower(),
            "models": models,
            "point_temps": point_temps,
            "entries": entries,
            "buckets": [{"name": b.name, "temp_c": b.temp_c} for b in ev.buckets if b.temp_c is not None],
            "source": "forward_watch_snapshot",
            "snapshot_ts": snap.get("ts_utc"),
            "snapshot_basket": snap.get("basket_cost"),
        }
        print(
            f"+case {slug} winner={winner.name} basket_snap={snap.get('basket_cost')} dna_snap={snap.get('dna_take')}",
            flush=True,
        )
        if not args.dry_run:
            cases.append(case)
            have.add(slug)
            added += 1

    if added and not args.dry_run:
        CASES.parent.mkdir(parents=True, exist_ok=True)
        CASES.write_text(json.dumps(cases, indent=2), encoding="utf-8")

    after_takes = take_income_wr80(cases)
    wins = sum(1 for t in after_takes if t.get("win") or float(t.get("pnl") or 0) > 0)
    n = len(after_takes)
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "snapshots": len(snaps),
        "resolved_checked": resolved_checked,
        "cases_added": added,
        "takes_before": before_n,
        "takes_after": n,
        "delta_n": n - before_n,
        "wins": wins,
        "wr_point": round(wins / n, 4) if n else 0.0,
        "wilson95_lower": round(_wilson_lower(wins, n), 4),
        "by_city": dict(Counter(t.get("city") for t in after_takes)),
        "note_es": "Forward snapshots→cases. CLOB history no cubre pre-julio; esta es la vía de n.",
    }
    if not args.dry_run:
        write_evidence_progress()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "FORWARD_RESOLVE_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
