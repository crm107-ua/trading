import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_local"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _write_gz(path: Path, rows: list[dict]) -> None:
    import gzip

    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
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
    data_first: datetime,
    data_last: datetime,
    step_s: int = 5,
) -> Path:
    root = DATA / dataset_id
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
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

    a = int(data_first.timestamp() * 1e9)
    b = int(data_last.timestamp() * 1e9)
    rows = _mk_rows(a, b, step_s=step_s)
    _write_gz(root / "btc" / "2026-01-01" / "00.jsonl.gz", rows)
    _write_gz(root / "clob" / "2026-01-01" / "00.jsonl.gz", rows)
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
    out = json.loads(p.stdout)
    return p.returncode, out


def test_validate_phase_a_anchored_span_cases():
    now = datetime.now(timezone.utc)
    phase_start = now - timedelta(days=31)
    phase_end = phase_start + timedelta(minutes=60)
    warmup_s = 60
    span_start = phase_start + timedelta(seconds=warmup_s)

    # Tail gap => fail (silent death penalizes)
    _write_dataset(
        "pytest_regress_tail_gap",
        phase_start=phase_start,
        phase_end=phase_end,
        warmup_s=warmup_s,
        data_first=span_start,
        data_last=phase_end - timedelta(minutes=20),
    )
    code, out = _run_validate("pytest_regress_tail_gap")
    assert code == 1
    assert out["pass"] is False

    # Head gap => fail
    _write_dataset(
        "pytest_regress_head_gap",
        phase_start=phase_start,
        phase_end=phase_end,
        warmup_s=warmup_s,
        data_first=span_start + timedelta(minutes=10),
        data_last=phase_end - timedelta(minutes=1),
    )
    code, out = _run_validate("pytest_regress_head_gap")
    assert code == 1
    assert out["pass"] is False

    # Threshold exact ~95% => pass (>= threshold)
    # active_window_s = 3600-60=3540 => need 5% gaps => 177s tail gap
    _write_dataset(
        "pytest_regress_threshold_95",
        phase_start=phase_start,
        phase_end=phase_end,
        warmup_s=warmup_s,
        data_first=span_start,
        data_last=phase_end - timedelta(seconds=177),
        step_s=1,
    )
    code, out = _run_validate("pytest_regress_threshold_95")
    assert code == 0
    assert out["pass"] is True

    # Healthy => pass
    _write_dataset(
        "pytest_regress_healthy",
        phase_start=phase_start,
        phase_end=phase_end,
        warmup_s=warmup_s,
        data_first=span_start,
        data_last=phase_end,
    )
    code, out = _run_validate("pytest_regress_healthy")
    assert code == 0
    assert out["pass"] is True

