#!/usr/bin/env python3
"""Validate phase A uptime >= threshold after >= min wall-clock days."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import gzip
from datetime import timedelta

from polymarket.research.collectors.recording_common import (
    SMOKE_DATASET_ID,
    is_smoke_dataset,
    load_phase_a_config,
    resolve_data_root,
)


def _gap_seconds(gaps: list[dict]) -> float:
    total = 0.0
    for g in gaps:
        total += (int(g["end_ns"]) - int(g["start_ns"])) / 1e9
    return total


def _inactive_seconds(clob_feed: dict) -> float:
    """Gamma inter-window gaps — excluded from uptime penalty."""
    return _gap_seconds(clob_feed.get("market_inactive_periods") or [])


def _all_gz_files(root: Path, feed: str) -> list[Path]:
    d = root / feed
    if not d.exists():
        return []
    return sorted(d.rglob("*.jsonl.gz"))


def _iter_recv_ts_ns(files: list[Path]):
    for path in files:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    ts = int(row.get("recv_ts_ns", 0))
                    if ts > 0:
                        yield ts
        except EOFError:
            continue


def _gap_seconds_from_timestamps(
    files: list[Path],
    *,
    inactive_periods: list[dict] | None = None,
    threshold_s: float = 10.0,
) -> tuple[float, int, int | None, int | None]:
    inactive_periods = inactive_periods or []
    inactive = sorted(
        [(int(p["start_ns"]), int(p["end_ns"])) for p in inactive_periods if "start_ns" in p and "end_ns" in p],
        key=lambda x: x[0],
    )

    def is_inactive(ts_ns: int) -> bool:
        for a, b in inactive:
            if a <= ts_ns <= b:
                return True
        return False

    prev: int | None = None
    first: int | None = None
    last: int | None = None
    total_gap_s = 0.0
    gap_count = 0
    thr_ns = int(threshold_s * 1e9)
    for ts in _iter_recv_ts_ns(files):
        if is_inactive(ts):
            prev = None
            continue
        if first is None:
            first = ts
        if prev is not None:
            dt = ts - prev
            if dt > thr_ns:
                total_gap_s += dt / 1e9
                gap_count += 1
        prev = ts
        last = ts
    return total_gap_s, gap_count, first, last


def _edge_gaps_to_span(
    *,
    span_start_ns: int,
    span_end_ns: int,
    first_ts_ns: int | None,
    last_ts_ns: int | None,
    threshold_s: float,
) -> tuple[float, int]:
    """Penalize silence at the edges of the official span."""
    if first_ts_ns is None or last_ts_ns is None:
        # No data at all => full-span gap
        return (span_end_ns - span_start_ns) / 1e9, 1
    thr_ns = int(threshold_s * 1e9)
    total = 0.0
    count = 0
    head = first_ts_ns - span_start_ns
    if head > thr_ns:
        total += head / 1e9
        count += 1
    tail = span_end_ns - last_ts_ns
    if tail > thr_ns:
        total += tail / 1e9
        count += 1
    return total, count


def main() -> None:
    cfg = load_phase_a_config()
    root = resolve_data_root(cfg)
    if root.name == SMOKE_DATASET_ID or is_smoke_dataset(cfg):
        print(f"FAIL: validate_phase_a refuses smoke dataset '{root.name}'")
        sys.exit(3)
    manifest_path = root / "manifest.json"
    threshold = float(cfg.get("phase_a_uptime_threshold", 0.95))
    min_days = float(cfg.get("phase_a_min_wall_clock_days", 30))

    if not manifest_path.exists():
        print("FAIL: manifest missing")
        sys.exit(1)

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    phase_start = datetime.fromisoformat(data.get("phase_start_utc", data["started_utc"]).replace("Z", "+00:00"))
    phase_end_raw = data.get("phase_end_utc")
    if phase_end_raw:
        phase_end = datetime.fromisoformat(phase_end_raw.replace("Z", "+00:00"))
    else:
        phase_end = phase_start + timedelta(days=min_days)

    elapsed_days = (datetime.now(timezone.utc) - phase_start).total_seconds() / 86400
    if elapsed_days < min_days:
        print(f"PENDING: only {elapsed_days:.1f}d elapsed (need {min_days}d)")
        sys.exit(2)

    feeds = data.get("feeds") or {}
    clob_feed = feeds.get("clob") or {}
    # Validation span is anchored (infalsificable).
    span_s = (phase_end - phase_start).total_seconds()
    inactive_s = _inactive_seconds(clob_feed)
    warmup_s = int(data.get("warmup_seconds", cfg.get("phase_a_warmup_seconds", 1800)))
    active_window_s = max(span_s - inactive_s - warmup_s, 1.0)

    # Source of truth = inferred gaps from timestamps (not daemon marks)
    btc_files = _all_gz_files(root, "btc")
    clob_files = _all_gz_files(root, "clob")
    btc_gap_s, btc_gap_n, btc_first, btc_last = _gap_seconds_from_timestamps(btc_files, threshold_s=10.0)
    clob_gap_s, clob_gap_n, clob_first, clob_last = _gap_seconds_from_timestamps(
        clob_files,
        inactive_periods=clob_feed.get("market_inactive_periods") or [],
        threshold_s=10.0,
    )
    span_start_ns = int((phase_start + timedelta(seconds=warmup_s)).timestamp() * 1e9)
    span_end_ns = int(phase_end.timestamp() * 1e9)
    btc_edge_s, btc_edge_n = _edge_gaps_to_span(
        span_start_ns=span_start_ns,
        span_end_ns=span_end_ns,
        first_ts_ns=btc_first,
        last_ts_ns=btc_last,
        threshold_s=10.0,
    )
    clob_edge_s, clob_edge_n = _edge_gaps_to_span(
        span_start_ns=span_start_ns,
        span_end_ns=span_end_ns,
        first_ts_ns=clob_first,
        last_ts_ns=clob_last,
        threshold_s=10.0,
    )
    btc_gap_s += btc_edge_s
    clob_gap_s += clob_edge_s
    btc_gap_n += btc_edge_n
    clob_gap_n += clob_edge_n
    avg_gap = (btc_gap_s + clob_gap_s) / 2
    uptime = 1.0 - (avg_gap / active_window_s) if active_window_s > 0 else 0.0
    ok = uptime >= threshold

    report = {
        "elapsed_days": round(elapsed_days, 2),
        "phase_start_utc": phase_start.isoformat(),
        "phase_end_utc": phase_end.isoformat(),
        "warmup_seconds": warmup_s,
        "uptime_estimate": round(uptime, 4),
        "threshold": threshold,
        "pass": ok,
        "inferred_gap_seconds_avg": round(avg_gap, 1),
        "inferred_gap_counts": {"btc": btc_gap_n, "clob": clob_gap_n},
        "gamma_inactive_seconds": round(inactive_s, 1),
        "active_window_denominator_seconds": round(active_window_s, 1),
        "note": "Anchored span (phase_start/end) + warmup; gaps inferred from recv_ts_ns incl. tail silence",
    }
    out = root / "phase_a_validation.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
