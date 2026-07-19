#!/usr/bin/env python3
"""Sesión REAL micro 2.5€ — siempre restaura SAFE al salir.

    python3 -m polymarket.research.local_lab.run_real_micro25 --minutes 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "real_micro25"
KILL_MARKERS = (
    "FLATTEN_WRONG_TOKEN",
    "DUST_STUCK",
    "KILL_SESSION",
    "KILL_DAY",
    "POST_ERR",
    "balance is not enough",
)


def _snap_balance() -> float | None:
    try:
        from polymarket.src.execution.clob_live import ClobLiveClient

        cli = ClobLiveClient()
        cli.connect()
        return float(cli.balance_collateral_usdc())
    except Exception as e:
        print(f"BAL_ERR {type(e).__name__}: {e}", flush=True)
        return None


def _force_safe() -> None:
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    print("SAFE restored: ARMED=0 DRY_RUN=1", flush=True)


async def async_main(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bal_before = _snap_balance()
    print(f"BALANCE_BEFORE={bal_before}", flush=True)

    os.environ["POLY_LIVE_ARMED"] = "1"
    os.environ["POLY_LIVE_DRY_RUN"] = "0"  # REAL
    os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = "2.5"
    os.environ["POLY_LIVE_DRY_SMOKE_POST"] = "0"
    os.environ.pop("POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC", None)

    from polymarket.src.execution.clob_live import read_gates
    from polymarket.src.execution.live_policy import validate_real_start

    g = read_gates()
    print(
        f"ARM armed={g.armed} dry_run={g.dry_run} max_cap={g.max_capital_usdc}",
        flush=True,
    )
    if g.dry_run or not g.armed:
        _force_safe()
        raise RuntimeError("ABORT: no se armó REAL (dry aún activo o no ARMED)")

    ok, msg = validate_real_start(2.5, bal_before)
    print(f"VALIDATE {ok} {msg}", flush=True)
    if not ok:
        _force_safe()
        raise RuntimeError(f"ABORT validate: {msg}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sid = f"REAL_micro25_{stamp}"
    cfg = POLY / "config" / "maker_demo_promo_pulse_micro2.json"

    print(
        f"=== REAL START capital=2.5 minutes={args.minutes} sid={sid} ===",
        flush=True,
    )
    t0 = time.time()
    report: dict = {}
    try:
        from polymarket.research.local_lab.live_maker import run_live_session

        report = await run_live_session(
            minutes=float(args.minutes),
            config_path=cfg,
            session_id=sid,
            strategy="maker_fusion",
            desk_line_id=1,
        )
    except Exception as e:
        print(f"REAL_ERR {type(e).__name__}: {e}", flush=True)
        report = {"error": f"{type(e).__name__}: {e}", "verdict": "REAL_ERROR"}
    finally:
        # Cancelar todo y SAFE
        try:
            from polymarket.src.execution.clob_live import ClobLiveClient

            cli = ClobLiveClient()
            cli.connect()
            print("CANCEL_ALL", cli.cancel_all(), flush=True)
        except Exception as e:
            print(f"CANCEL_ERR {type(e).__name__}: {e}", flush=True)
        _force_safe()

    bal_after = _snap_balance()
    elapsed = time.time() - t0
    danger = []
    # scan session log/report
    session_dir = report.get("session_dir")
    if session_dir:
        dec = Path(session_dir) / "decisions.jsonl"
        # also check stdout was printed; scan report fields
    if report.get("inventory_residual") and abs(float(report.get("inventory_residual") or 0)) > 0.01:
        danger.append("inventory_residual")
    if report.get("verdict") not in ("LIVE_ONCHAIN", "LIVE_DRY_RUN"):
        # LIVE_ONCHAIN expected for real
        pass
    if report.get("verdict") == "LIVE_DRY_RUN":
        danger.append("was_dry_not_real")

    out = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "sid": sid,
        "minutes": float(args.minutes),
        "elapsed_s": round(elapsed, 1),
        "balance_before_pusd": bal_before,
        "balance_after_pusd": bal_after,
        "balance_delta": (
            None
            if bal_before is None or bal_after is None
            else round(float(bal_after) - float(bal_before), 4)
        ),
        "report": report,
        "danger": danger,
        "live_flags_now": {
            "POLY_LIVE_ARMED": os.environ.get("POLY_LIVE_ARMED"),
            "POLY_LIVE_DRY_RUN": os.environ.get("POLY_LIVE_DRY_RUN"),
        },
        "ok": bool(
            report.get("verdict") == "LIVE_ONCHAIN"
            and abs(float(report.get("inventory_residual") or 0)) < 0.01
            and not danger
        ),
    }
    path = OUT / f"real_{stamp}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    (OUT / "real_latest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in (
        "ok", "balance_before_pusd", "balance_after_pusd", "balance_delta",
        "danger", "live_flags_now"
    )}, indent=2), flush=True)
    print(
        f"SESSION verdict={report.get('verdict')} net={report.get('net_session_usdc')} "
        f"fills={report.get('fills')} residual={report.get('inventory_residual')}",
        flush=True,
    )
    print(f"REPORT -> {path}", flush=True)
    return 0 if out["ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=float, default=15.0)
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
