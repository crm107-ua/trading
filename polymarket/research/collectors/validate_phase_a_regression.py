#!/usr/bin/env python3
"""
Regression harness for validate_phase_a anchored-span semantics.

Creates 4 synthetic datasets (isolated under data_local/) and runs
validate_phase_a against each, printing the outputs.

This is local-only, no prod.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data_local"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _write_gz(feed_dir: Path, name: str, rows: list[dict]) -> None:
    feed_dir.mkdir(parents=True, exist_ok=True)
    p = feed_dir / name
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")


def _mk_rows(start_ns: int, end_ns: int, step_s: int = 5) -> list[dict]:
    out = []
    step = step_s * 1_000_000_000
    t = start_ns
    while t <= end_ns:
        out.append({"recv_ts_ns": t, "x": 1})
        t += step
    return out


def _write_dataset(
    dataset_id: str,
    *,
    phase_start: datetime,
    phase_end: datetime,
    warmup_s: int,
    data_first: datetime | None,
    data_last: datetime | None,
    step_s: int = 5,
) -> Path:
    root = DATA / dataset_id
    if root.exists():
        shutil.rmtree(root)
    (root / "btc").mkdir(parents=True, exist_ok=True)
    (root / "clob").mkdir(parents=True, exist_ok=True)

    manifest = {
        "phase": "A",
        "hypothesis": 16,
        "dataset_id": dataset_id,
        "smoke_test": False,
        "official_phase_a": False,
        "started_utc": _iso(phase_start),
        "phase_start_utc": _iso(phase_start),
        "phase_end_utc": _iso(phase_end),
        "warmup_seconds": warmup_s,
        "feeds": {"clob": {"market_inactive_periods": []}},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if data_first is not None and data_last is not None:
        a = int(data_first.timestamp() * 1e9)
        b = int(data_last.timestamp() * 1e9)
        rows = _mk_rows(a, b, step_s=step_s)
    else:
        rows = []

    # single file per feed is enough
    _write_gz(root / "btc" / "2026-01-01", "00.jsonl.gz", rows)
    _write_gz(root / "clob" / "2026-01-01", "00.jsonl.gz", rows)
    return root


def _run_validate(dataset_id: str) -> tuple[int, dict]:
    env = os.environ.copy()
    env["POLY_DATASET"] = dataset_id
    p = subprocess.run(
        [sys.executable, "-m", "polymarket.research.collectors.validate_phase_a"],
        cwd=str(ROOT.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    # validate_phase_a prints JSON on success/fail; on pending it's text.
    out = {}
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        out = {"stdout": p.stdout, "stderr": p.stderr}
    return p.returncode, out


def main() -> None:
    now = datetime.now(timezone.utc)
    # Make phase_start far enough in the past to satisfy min_days check
    phase_start = now - timedelta(days=31)
    span_minutes = 60
    phase_end = phase_start + timedelta(minutes=span_minutes)
    warmup_s = 60

    span_start = phase_start + timedelta(seconds=warmup_s)

    cases = []

    # 1) Tail gap: data stops early, silence until phase_end => penalize tail
    cases.append(
        ("tail_gap", span_start, phase_end - timedelta(minutes=20), False)
    )
    # 2) Head gap: data starts late, gap from span_start => penalize head
    cases.append(
        ("head_gap", span_start + timedelta(minutes=10), phase_end - timedelta(minutes=1), False)
    )
    # 3) Threshold: make uptime ~0.95 exactly by tail gap size
    # active_window_s = span - warmup (no inactive) = 3600-60=3540
    # need avg_gap_s = 0.05*3540 = 177s (tail)
    tail_s = 177
    cases.append(
        ("threshold_95", span_start, phase_end - timedelta(seconds=tail_s), True, 1)
    )
    # 4) Healthy: continuous data full span
    cases.append(
        ("healthy", span_start, phase_end, True, 5)
    )

    print("=== validate_phase_a anchored-span regression ===")
    for item in cases:
        if len(item) == 4:
            name, first, last, expect_pass = item
            step_s = 5
        else:
            name, first, last, expect_pass, step_s = item
        ds = f"regress_{name}"
        _write_dataset(
            ds,
            phase_start=phase_start,
            phase_end=phase_end,
            warmup_s=warmup_s,
            data_first=first,
            data_last=last,
            step_s=step_s,
        )
        code, out = _run_validate(ds)
        ok = bool(out.get("pass")) if isinstance(out, dict) else False
        print()
        print(f"[{name}] dataset={ds} expected_pass={expect_pass} exit={code} pass={ok}")
        print(json.dumps(out, indent=2))

    print("\nDone.")


if __name__ == "__main__":
    main()

