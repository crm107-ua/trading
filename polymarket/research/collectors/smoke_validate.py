#!/usr/bin/env python3
"""Smoke test validation -- 7 criteria from PHASE_A smoke protocol."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

from datetime import datetime, timezone

from polymarket.research.collectors.recording_common import load_phase_a_config, resolve_data_root


def _iter_recv_ts_ns(files: list[Path], *, stats: dict, feed: str):
    """Stream recv_ts_ns from .jsonl.gz files.

    We tolerate truncation/corruption (expected on kills), but we DO count it.
    """
    for path in files:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                try:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            stats["bad_json_lines"] = stats.get("bad_json_lines", 0) + 1
                            continue
                        ts = int(row.get("recv_ts_ns", 0))
                        if ts > 0:
                            yield ts
                except Exception:
                    # gzip stream corruption mid-file/tail — ignore rest but count it
                    stats["truncated_files"] = stats.get("truncated_files", 0) + 1
                    stats.setdefault("truncated_paths", []).append(str(path))
                    continue
        except Exception:
            stats["unreadable_files"] = stats.get("unreadable_files", 0) + 1
            continue


def _gap_seconds_from_timestamps(
    files: list[Path],
    *,
    inactive_periods: list[dict] | None = None,
    threshold_s: float = 10.0,
    feed: str,
) -> tuple[float, int]:
    """
    Reconstruct gaps purely from data timestamps.

    This is the source of truth: a crash / kill -9 cannot "mark" its own death.
    inactive_periods (Gamma inter-window listing gaps) are excluded from gap accounting.
    """
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
    total_gap_s = 0.0
    gap_count = 0
    thr_ns = int(threshold_s * 1e9)
    stats = {"truncated_files": 0, "bad_json_lines": 0, "unreadable_files": 0, "truncated_paths": []}
    for ts in _iter_recv_ts_ns(files, stats=stats, feed=feed):
        if is_inactive(ts):
            prev = None
            continue
        if prev is not None:
            dt = ts - prev
            if dt > thr_ns:
                total_gap_s += dt / 1e9
                gap_count += 1
        prev = ts
    return total_gap_s, gap_count, stats


def _read_jsonl_gz(path: Path, max_lines: int = 5000) -> list[dict]:
    rows: list[dict] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= max_lines:
                break
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _all_gz_files(root: Path, feed: str) -> list[Path]:
    d = root / feed
    if not d.exists():
        return []
    return sorted(d.rglob("*.jsonl.gz"))


def main() -> None:
    cfg = load_phase_a_config()
    root = resolve_data_root(cfg)
    manifest_path = root / "manifest.json"
    report: dict = {"root": str(root), "checks": {}, "pass": True}

    if not manifest_path.exists():
        print("FAIL: no manifest")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report["manifest"] = manifest

    if not manifest.get("smoke_test"):
        report["checks"]["smoke_flag"] = "FAIL: manifest.smoke_test != true"
        report["pass"] = False
    else:
        report["checks"]["smoke_flag"] = "OK"

    btc_files = _all_gz_files(root, "btc")
    clob_files = _all_gz_files(root, "clob")
    report["checks"]["files_exist"] = (
        "OK" if btc_files and clob_files else f"FAIL btc={len(btc_files)} clob={len(clob_files)}"
    )
    if not btc_files or not clob_files:
        report["pass"] = False

    # Hour rotation: need >=2 distinct hour paths OR duration note in manifest
    btc_hours = {f.parent.name for f in btc_files}
    report["checks"]["hour_rotation"] = (
        "OK" if len(btc_hours) >= 2 or len(btc_files) >= 2 else f"WARN hours={len(btc_hours)}"
    )

    # JSON validity + monotonic recv_ts_ns + top-10
    for feed, files in [("btc", btc_files), ("clob", clob_files)]:
        if not files:
            continue
        rows = _read_jsonl_gz(files[-1], 200)
        if not rows:
            report["checks"][f"{feed}_json"] = "FAIL empty file"
            report["pass"] = False
            continue
        recv = [r.get("recv_ts_ns", 0) for r in rows]
        mono = all(recv[i] <= recv[i + 1] for i in range(len(recv) - 1))
        report["checks"][f"{feed}_json"] = "OK" if mono else "FAIL non-monotonic recv_ts_ns"
        if not mono:
            report["pass"] = False
        if feed == "clob":
            over = sum(
                1
                for r in rows
                if len(r.get("bids") or []) > 10 or len(r.get("asks") or []) > 10
            )
            report["checks"]["top_10_levels"] = (
                "OK" if over == 0 else f"FAIL {over} snapshots exceed 10 levels"
            )
            if over:
                report["pass"] = False

    # Clock alignment: compare last btc vs clob recv_ts_ns
    if btc_files and clob_files:
        br = _read_jsonl_gz(btc_files[-1], 1)
        cr = _read_jsonl_gz(clob_files[-1], 1)
        if br and cr:
            diff_ms = abs(br[-1]["recv_ts_ns"] - cr[-1]["recv_ts_ns"]) / 1e6
            report["checks"]["clock_alignment_ms"] = (
                f"OK diff={diff_ms:.0f}ms" if diff_ms < 60_000 else f"WARN diff={diff_ms:.0f}ms"
            )

    # Market switches
    clob_feed = (manifest.get("feeds") or {}).get("clob") or {}
    switches = clob_feed.get("market_switches") or []
    report["checks"]["market_switches"] = (
        f"OK count={len(switches)}" if len(switches) >= 1 else "FAIL no market switch logged"
    )
    if len(switches) < 1:
        report["pass"] = False

    # Gaps (kill/relaunch test)
    # Source of truth = reconstructed gaps from timestamps (infalsificable)
    inactive_periods = clob_feed.get("market_inactive_periods") or []
    btc_gap_s, btc_gap_n, btc_stats = _gap_seconds_from_timestamps(btc_files, threshold_s=10.0, feed="btc")
    clob_gap_s, clob_gap_n, clob_stats = _gap_seconds_from_timestamps(
        clob_files, inactive_periods=inactive_periods, threshold_s=10.0, feed="clob"
    )
    report["data_integrity"] = {"btc": btc_stats, "clob": clob_stats}
    report["checks"]["gaps_recorded"] = (
        f"OK inferred_gaps btc={btc_gap_n} ({btc_gap_s:.0f}s) clob={clob_gap_n} ({clob_gap_s:.0f}s)"
        if (btc_gap_n + clob_gap_n) >= 1
        else "FAIL no inferred gaps >10s (kill/relaunch test?)"
    )
    if (btc_gap_n + clob_gap_n) < 1:
        report["pass"] = False

    # Check 8: 5m window coverage from observed window_start timestamps
    # (does not depend on wall-clock elapsed nor on Gamma listing gaps)
    starts = []
    for sw in switches:
        ws = sw.get("window_start")
        if not ws:
            continue
        try:
            starts.append(datetime.fromisoformat(ws.replace("Z", "+00:00")))
        except ValueError:
            continue
    if len(starts) >= 2:
        starts = sorted(set(starts))
        span_s = (starts[-1] - starts[0]).total_seconds()
        expected_windows = int(span_s // 300) + 1
        switch_count = len(starts)
        coverage = switch_count / max(expected_windows, 1)
        report["checks"]["window_coverage"] = (
            f"OK {coverage:.0%} ({switch_count}/{expected_windows} windows)"
            if coverage >= 0.80
            else f"FAIL {coverage:.0%} ({switch_count}/{expected_windows} windows, need >=80%)"
        )
        if coverage < 0.80:
            report["pass"] = False
    elif len(starts) == 1:
        report["checks"]["window_coverage"] = "WARN only 1 window observed"
    else:
        report["checks"]["window_coverage"] = "WARN no window_start timestamps"

    out = root / "smoke_validation.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
