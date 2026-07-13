#!/usr/bin/env python3
"""
Orchestrate local smoke test (~90 min) into data_local/smoke_test/ only.

Official phase A (30d) starts on Hetzner PM2 into phase_a_16/ -- never mix.

Windows:
  $env:PYTHONUTF8 = "1"
  powercfg /change standby-timeout-ac 0
  python -m polymarket.research.collectors.run_smoke_test
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data_local"


def _clean_smoke_dirs() -> None:
    import stat

    def _on_rm_error(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    for name in ("smoke_test", "phase_a_16"):
        p = DATA / name
        if not p.exists():
            continue
        for attempt in range(3):
            try:
                shutil.rmtree(p, onexc=_on_rm_error)
                print(f"Removed {p}")
                break
            except PermissionError:
                if attempt < 2:
                    time.sleep(2)
                else:
                    print(f"WARN: could not fully remove {p} (files locked)")


def _popen_daemon(module: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["POLY_DATASET"] = "smoke_test"
    env["POLY_MANIFEST_INTERVAL_S"] = "60"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        [sys.executable, "-m", module],
        cwd=str(ROOT.parent),
        env=env,
    )


def _stop(proc: subprocess.Popen | None, label: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    print(f"Stopping {label} pid={proc.pid}")
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=int, default=90, help="Smoke duration (default 90)")
    p.add_argument("--skip-kill-test", action="store_true")
    args = p.parse_args()

    os.environ["PYTHONUTF8"] = "1"
    _clean_smoke_dirs()

    btc = _popen_daemon("polymarket.research.collectors.daemon_btc_feed")
    clob = _popen_daemon("polymarket.research.collectors.daemon_clob_recorder")
    print(f"Started btc pid={btc.pid} clob pid={clob.pid} -> data_local/smoke_test/")

    t0 = time.monotonic()
    kill_at = 20 * 60 if not args.skip_kill_test else None
    killed_clob = False

    try:
        while time.monotonic() - t0 < args.minutes * 60:
            if kill_at and not killed_clob and time.monotonic() - t0 >= kill_at:
                print("Kill/relaunch test: stopping clob for 120s")
                _stop(clob, "clob")
                time.sleep(120)
                clob = _popen_daemon("polymarket.research.collectors.daemon_clob_recorder")
                print(f"Relaunched clob pid={clob.pid}")
                killed_clob = True
            if btc.poll() is not None:
                print(f"WARN btc exited code={btc.returncode}, restarting")
                btc = _popen_daemon("polymarket.research.collectors.daemon_btc_feed")
            if clob.poll() is not None:
                print(f"WARN clob exited code={clob.returncode}, restarting")
                clob = _popen_daemon("polymarket.research.collectors.daemon_clob_recorder")
            time.sleep(10)
    finally:
        _stop(btc, "btc")
        _stop(clob, "clob")

    env = os.environ.copy()
    env["POLY_DATASET"] = "smoke_test"
    env["PYTHONUTF8"] = "1"

    print("\n--- health_check (feeds should be stale after stop) ---")
    subprocess.run(
        [sys.executable, "-m", "polymarket.research.collectors.health_check"],
        cwd=str(ROOT.parent),
        env=env,
    )

    print("\n--- smoke_validate ---")
    r = subprocess.run(
        [sys.executable, "-m", "polymarket.research.collectors.smoke_validate"],
        cwd=str(ROOT.parent),
        env=env,
    )

    report_path = DATA / "smoke_test" / "smoke_validation.json"
    if report_path.exists():
        print("\nReport:", report_path.read_text(encoding="utf-8")[:2000])

    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
