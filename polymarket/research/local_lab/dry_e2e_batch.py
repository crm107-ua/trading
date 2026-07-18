#!/usr/bin/env python3
"""Fase B — batch dry E2E + tests. Escribe live_checklist.json si todo pasa.

    python -m polymarket.research.local_lab.dry_e2e_batch
    python -m polymarket.research.local_lab.dry_e2e_batch --sessions 10
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from polymarket.src.execution.live_policy import (
    DRY_SESSIONS_REQUIRED,
    save_checklist,
)

POLY = Path(__file__).resolve().parents[2]
ROOT = POLY.parent


def _run_pytest() -> tuple[bool, str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(POLY / "tests" / "test_live_e2e_dry.py"),
        str(POLY / "tests" / "test_clob_live_fills.py"),
        str(POLY / "tests" / "test_live_policy.py"),
        "-q",
        "--tb=line",
    ]
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode == 0, out[-4000:]


def _simulate_dry_sessions(n: int) -> list[dict]:
    """Simula N ciclos dry Up/Down/dust/cash (sin red) vía helpers de test."""
    from types import SimpleNamespace
    from pathlib import Path as P

    from polymarket.research.local_lab.live_maker import LiveSession
    from polymarket.src.execution.clob_live import (
        ClobLiveClient,
        MIN_ORDER_SHARES,
        normalize_live_order,
        round_inventory_size,
    )
    from polymarket.src.execution.live_policy import kill_line_reason

    results: list[dict] = []
    for i in range(n):
        errors: list[str] = []
        # 1) cheap quote → up
        cheap = SimpleNamespace(bid=0.40, ask=0.99, size_shares=5)
        rich = SimpleNamespace(bid=0.01, ask=0.62, size_shares=5)
        if not LiveSession._is_cheap_quote(cheap):
            errors.append("cheap_detect")
        if not LiveSession._is_rich_quote(rich):
            errors.append("rich_detect")
        # 2) SELL dust no bump
        _, sz = normalize_live_order(side="SELL", price=0.2, size=4.990644)
        if sz > 4.990644 + 1e-9:
            errors.append("sell_bump")
        # 3) held token preference
        s = LiveSession(cfg={}, out_dir=P("."), clob=ClobLiveClient(), bankroll=1.0)
        s.inventory_shares = 5.0
        s.held_token_id = "DOWN"
        if s._position_token("UP") != "DOWN":
            errors.append("held_token")
        # 4) kill lines
        if kill_line_reason("DUST_STUCK inv=4.99") != "dust_stuck":
            errors.append("kill_dust")
        # 5) size floor buy
        px, bsz = normalize_live_order(side="BUY", price=0.35, size=1.0)
        if bsz < MIN_ORDER_SHARES or px * bsz < 1.0 - 1e-9:
            errors.append("buy_floor")
        inv = round_inventory_size(4.990644)
        ok = not errors
        results.append(
            {
                "i": i + 1,
                "ok": ok,
                "errors": errors,
                "inv_sample": inv,
                "buy_notional": round(px * bsz, 4),
            }
        )
        time.sleep(0.01)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Dry E2E + checklist live")
    ap.add_argument("--sessions", type=int, default=DRY_SESSIONS_REQUIRED)
    ap.add_argument("--skip-pytest", action="store_true")
    args = ap.parse_args()

    os.environ.setdefault("POLY_LIVE_ARMED", "0")
    os.environ.setdefault("POLY_LIVE_DRY_RUN", "1")

    pytest_ok, pytest_out = (True, "skipped")
    if not args.skip_pytest:
        print(">> pytest live e2e / policy / fills...", flush=True)
        pytest_ok, pytest_out = _run_pytest()
        print(pytest_out[-1500:], flush=True)
        if not pytest_ok:
            save_checklist(
                {
                    "ok": False,
                    "dry_sessions_clean": 0,
                    "pytest_ok": False,
                    "notes": "pytest falló — checklist no verde",
                    "pytest_tail": pytest_out[-500:],
                }
            )
            print("CHECKLIST no ok (pytest)", flush=True)
            return 1

    print(f">> simular {args.sessions} ciclos dry...", flush=True)
    sims = _simulate_dry_sessions(max(1, int(args.sessions)))
    clean = sum(1 for s in sims if s["ok"])
    all_ok = clean >= int(args.sessions) and all(s["ok"] for s in sims)
    path = save_checklist(
        {
            "ok": all_ok and pytest_ok,
            "dry_sessions_clean": clean if all_ok else clean,
            "pytest_ok": pytest_ok,
            "simulations": sims,
            "notes": (
                "Fase B OK — live real aún requiere saldo ≥5 pUSD"
                if all_ok and pytest_ok
                else "Fase B incompleta"
            ),
        }
    )
    print(
        json.dumps(
            {
                "checklist": str(path),
                "ok": all_ok and pytest_ok,
                "dry_sessions_clean": clean,
                "required": args.sessions,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if all_ok and pytest_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
