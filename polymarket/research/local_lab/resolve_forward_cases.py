#!/usr/bin/env python3
"""
Resolve forward quote snapshots into DNA cases when markets close.

Live WATCH writes telemetry/quote_snapshots.jsonl (asks we actually saw).
This job turns resolved snapshots into weather_optimize/cases.json rows and
re-scores DNA takes — the only scalable evidence path (CLOB history is gone
for pre-July markets).

Also UPDATES existing cases when a market newly closes (winner refresh +
prefer forward-snapshot entries when available).

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
        score = (1 if r.get("dna_take") else 0, -float(r.get("basket_cost") or 99))
        score_cur = (1 if cur.get("dna_take") else 0, -float(cur.get("basket_cost") or 99))
        if score > score_cur:
            best[slug] = r
    return best


def _case_from_snap(slug: str, snap: dict[str, Any], ev: Any, winner: Any) -> dict[str, Any] | None:
    entries = {str(k): float(v) for k, v in (snap.get("entries") or {}).items() if v is not None}
    if len(entries) < 3:
        return None
    models = snap.get("models") or {}
    if len(models) < 2:
        return None
    point_temps = sorted({b.temp_c for b in ev.buckets if b.temp_c is not None})
    gates = snap.get("gates") if isinstance(snap.get("gates"), dict) else {}
    return {
        "slug": slug,
        "city": snap.get("city") or ev.city,
        "day": snap.get("day") or (ev.day.isoformat() if ev.day else None),
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
        "gates_at_snap": gates or None,
        "dna_take_at_snap": bool(snap.get("dna_take")),
        "resolved_closed": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cases = json.loads(CASES.read_text(encoding="utf-8")) if CASES.exists() else []
    by_slug = {c["slug"]: i for i, c in enumerate(cases) if c.get("slug")}
    before_takes = take_income_wr80(cases)
    before_n = len(before_takes)

    snaps = _best_snap_per_slug(_load_snaps())
    added = 0
    updated = 0
    resolved_checked = 0
    shadows: list[dict[str, Any]] = []

    from datetime import date, timedelta

    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=3)).isoformat()
    unfinished = [c["slug"] for c in cases if c.get("slug") and not c.get("resolved_closed")]
    recent_days = [
        c["slug"]
        for c in cases
        if c.get("slug") and str(c.get("day") or "") >= cutoff
    ]
    # Prefer forward snaps; refresh unfinished + last 3 days (not full archive every loop)
    slugs_to_check = set(snaps.keys()) | set(unfinished) | set(recent_days)

    for slug in sorted(slugs_to_check):
        snap = snaps.get(slug)
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

        if snap is not None:
            entries = {str(k): float(v) for k, v in (snap.get("entries") or {}).items() if v is not None}
            gates = snap.get("gates") if isinstance(snap.get("gates"), dict) else {}
            legs = snap.get("legs") or []
            leg_names = {str(x.get("name")) for x in legs if x.get("name") is not None}
            shadows.append(
                {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "slug": slug,
                    "city": snap.get("city") or ev.city,
                    "day": snap.get("day") or (ev.day.isoformat() if ev.day else None),
                    "winner": winner.name,
                    "winner_temp": winner.temp_c,
                    "snapshot_ts": snap.get("ts_utc"),
                    "snapshot_basket": snap.get("basket_cost"),
                    "dna_take_at_snap": bool(snap.get("dna_take")),
                    "gates_passed": gates.get("gates_passed"),
                    "waiting": gates.get("waiting"),
                    "ud": snap.get("ud"),
                    "winner_in_legs": winner.name in leg_names,
                    "winner_in_entries": winner.name in entries,
                    "shadow_press_hit": winner.name in leg_names,
                    "note": "shadow only — does not relax DNA; cases still filtered by take_income_wr80",
                }
            )

        if slug in by_slug:
            idx = by_slug[slug]
            cur = cases[idx]
            changed = False
            # Refresh winner if missing or different after true close
            if cur.get("winner") != winner.name or not cur.get("resolved_closed"):
                cur["winner"] = winner.name
                cur["winner_temp"] = winner.temp_c
                cur["winner_open_high"] = "or higher" in (winner.name or "").lower()
                cur["winner_open_low"] = "or below" in (winner.name or "").lower()
                cur["resolved_closed"] = True
                changed = True
            # Prefer live forward entries when we have a good snap (honest asks we saw)
            if snap is not None:
                built = _case_from_snap(slug, snap, ev, winner)
                if built is not None:
                    old_b = float(cur.get("snapshot_basket") or cur.get("basket_cost") or 99)
                    new_b = float(built.get("snapshot_basket") or 99)
                    # Upgrade entries if snap is DNA or strictly cheaper basket
                    if built.get("dna_take_at_snap") or new_b + 1e-12 < old_b or not cur.get("entries"):
                        for k in (
                            "entries",
                            "models",
                            "point_temps",
                            "buckets",
                            "snapshot_ts",
                            "snapshot_basket",
                            "gates_at_snap",
                            "dna_take_at_snap",
                            "source",
                        ):
                            if built.get(k) is not None:
                                cur[k] = built[k]
                        cur["source"] = "forward_watch_snapshot"
                        changed = True
            if changed and not args.dry_run:
                cases[idx] = cur
                updated += 1
                print(f"~update {slug} winner={winner.name}", flush=True)
            continue

        # New case from snap only
        if snap is None:
            continue
        case = _case_from_snap(slug, snap, ev, winner)
        if case is None:
            continue
        print(
            f"+case {slug} winner={winner.name} basket_snap={snap.get('basket_cost')} dna_snap={snap.get('dna_take')}",
            flush=True,
        )
        if not args.dry_run:
            cases.append(case)
            by_slug[slug] = len(cases) - 1
            added += 1

    if not args.dry_run and shadows:
        TELE.mkdir(parents=True, exist_ok=True)
        with (TELE / "shadow_resolves.jsonl").open("a", encoding="utf-8") as f:
            for s in shadows:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

    if (added or updated) and not args.dry_run:
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
        "cases_updated": updated,
        "shadows_logged": len(shadows),
        "takes_before": before_n,
        "takes_after": n,
        "delta_n": n - before_n,
        "wins": wins,
        "wr_point": round(wins / n, 4) if n else 0.0,
        "wilson95_lower": round(_wilson_lower(wins, n), 4),
        "by_city": dict(Counter(t.get("city") for t in after_takes)),
        "note_es": (
            "Forward snapshots→cases/updates + shadow_resolves. "
            "CLOB history no cubre pre-julio; esta es la vía de n."
        ),
    }
    if not args.dry_run:
        write_evidence_progress()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "FORWARD_RESOLVE_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
