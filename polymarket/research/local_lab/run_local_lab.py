#!/usr/bin/env python3
"""
Laboratorio local Polymarket — grabación + paper sin prod.

  python -m polymarket.research.local_lab.run_local_lab --record --paper --minutes 60
  python -m polymarket.research.local_lab.run_local_lab --paper --strategy wide_spread_probe --minutes 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from polymarket.src.ai.env_loader import load_repo_dotenv, require_nvidia_api_key

load_repo_dotenv()
require_nvidia_api_key()

from polymarket.research.local_lab.paper_maker import MAKER_CFG, run_paper_session

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent


def resolve_config_path(raw: str) -> Path:
    """Resolve maker JSON from trading/ or polymarket/ cwd (Windows-safe)."""
    p = Path(raw)
    if p.is_absolute():
        return p
    norm = p.as_posix().lstrip("./")
    candidates = [
        REPO_ROOT / norm,
        ROOT / norm,
        ROOT / "config" / p.name,
        REPO_ROOT / "polymarket" / "config" / p.name,
    ]
    if norm.startswith("polymarket/"):
        candidates.insert(0, REPO_ROOT / norm)
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(f"Config no encontrado: {raw} (probadas: {[str(c) for c in candidates[:3]]})")


def _start_recording() -> tuple[subprocess.Popen, subprocess.Popen]:
    env = os.environ.copy()
    env["POLY_DATASET"] = "local_lab"
    env["POLY_MANIFEST_INTERVAL_S"] = "60"
    env["PYTHONUTF8"] = "1"
    repo = ROOT.parent
    btc = subprocess.Popen(
        [sys.executable, "-m", "polymarket.research.collectors.daemon_btc_feed"],
        cwd=str(repo),
        env=env,
    )
    clob = subprocess.Popen(
        [sys.executable, "-m", "polymarket.research.collectors.daemon_clob_recorder"],
        cwd=str(repo),
        env=env,
    )
    return btc, clob


def _stop(*procs: subprocess.Popen | None) -> None:
    for p in procs:
        if p is None or p.poll() is not None:
            continue
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


async def main_async(args: argparse.Namespace) -> int:
    btc_proc = clob_proc = None
    try:
        if args.record:
            print("Recording -> data_local/local_lab/ (BTC + CLOB)")
            btc_proc, clob_proc = _start_recording()
            await asyncio.sleep(5)

        if args.paper:
            print(f"Paper session strategy={args.strategy} minutes={args.minutes}")
            cfg_path = resolve_config_path(args.config) if args.config else None
            print(f"Config: {cfg_path or MAKER_CFG}", flush=True)
            report = await run_paper_session(args.strategy, args.minutes, config_path=cfg_path)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            if report.get("fills", 0) == 0:
                print("WARN: 0 fills — normal en sesiones cortas; alargar o probar otra estrategia")

        if args.record and not args.paper:
            print(f"Recording {args.minutes} min — Ctrl+C para parar")
            await asyncio.sleep(args.minutes * 60)
    finally:
        _stop(btc_proc, clob_proc)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Lab local Polymarket (sin prod)")
    p.add_argument("--record", action="store_true", help="Grabar BTC+CLOB en local_lab/")
    p.add_argument("--paper", action="store_true", help="Paper maker virtual")
    p.add_argument(
        "--strategy",
        default="maker_16",
        choices=["maker_16", "wide_spread_probe", "tight_mid_fade", "maker_edge"],
    )
    p.add_argument("--minutes", type=float, default=30.0)
    p.add_argument(
        "--config",
        type=str,
        default="",
        help="Ruta a JSON de maker (ej. polymarket/config/maker_demo_100.json)",
    )
    args = p.parse_args()
    if not args.record and not args.paper:
        p.error("Indica --record y/o --paper")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
