#!/usr/bin/env python3
"""Sesión REAL micro5 — siempre restaura SAFE al salir.

    python -m polymarket.research.local_lab.run_real_micro25 --capital 5 --minutes 12 --config maker_demo_promo_pulse_micro5.json
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
    capital = float(args.capital)
    cfg_name = str(args.config)
    bal_before = _snap_balance()
    print(
        f"BALANCE_BEFORE={bal_before} capital={capital} cfg={cfg_name}",
        flush=True,
    )

    os.environ["POLY_LIVE_ARMED"] = "1"
    os.environ["POLY_LIVE_DRY_RUN"] = "0"
    os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = str(capital)
    os.environ["POLY_LIVE_DRY_SMOKE_POST"] = "0"
    os.environ.pop("POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC", None)

    from polymarket.src.execution.clob_live import read_gates
    from polymarket.src.execution.live_policy import geoblock_blocks_real, validate_real_start

    g = read_gates()
    print(
        f"ARM armed={g.armed} dry_run={g.dry_run} max_cap={g.max_capital_usdc}",
        flush=True,
    )
    if g.dry_run or not g.armed:
        _force_safe()
        raise RuntimeError("ABORT: no se armó REAL")

    geo_blocked, geo_msg = geoblock_blocks_real()
    print(f"GEOBLOCK_CHECK blocked={geo_blocked} {geo_msg}", flush=True)
    if geo_blocked:
        _force_safe()
        raise RuntimeError(f"ABORT geoblock: {geo_msg}")

    ok, msg = validate_real_start(capital, bal_before)
    print(f"VALIDATE {ok} {msg}", flush=True)
    if not ok:
        _force_safe()
        raise RuntimeError(f"ABORT validate: {msg}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sid = f"REAL_c5_{stamp}"
    cfg = POLY / "config" / cfg_name
    if not cfg.is_file():
        cfg = POLY / cfg_name

    print(
        f"=== REAL START capital={capital} minutes={args.minutes} "
        f"sid={sid} cfg={cfg.name} ===",
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
            capital_usdc=capital,
        )
    except Exception as e:
        print(f"REAL_ERR {type(e).__name__}: {e}", flush=True)
        report = {"error": f"{type(e).__name__}: {e}", "verdict": "REAL_ERROR"}
    finally:
        try:
            from polymarket.src.execution.clob_live import ClobLiveClient

            cli = ClobLiveClient()
            cli.connect()
            print("CANCEL_ALL", cli.cancel_all(), flush=True)
        except Exception as e:
            print(f"CANCEL_ERR {type(e).__name__}: {e}", flush=True)
        _force_safe()

    bal_after = _snap_balance()
    residual = abs(float(report.get("inventory_residual") or 0))
    danger = list(report.get("session_danger") or [])
    if residual > 0.01 and "inventory_residual" not in danger:
        danger.append("inventory_residual")
    if report.get("verdict") == "LIVE_DRY_RUN":
        danger.append("was_dry_not_real")

    out = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "sid": sid,
        "capital_usdc": capital,
        "config": cfg_name,
        "minutes": float(args.minutes),
        "elapsed_s": round(time.time() - t0, 1),
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
            and residual < 0.01
            and "unclosed_position_at_session_end" not in danger
            and "inventory_residual" not in danger
        ),
    }
    path = OUT / f"real_{stamp}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    (OUT / "real_latest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: out[k]
                for k in (
                    "ok",
                    "balance_before_pusd",
                    "balance_after_pusd",
                    "balance_delta",
                    "danger",
                    "live_flags_now",
                )
            },
            indent=2,
        ),
        flush=True,
    )
    print(
        f"SESSION verdict={report.get('verdict')} net={report.get('net_session_usdc')} "
        f"fills={report.get('fills')} residual={report.get('inventory_residual')}",
        flush=True,
    )
    print(f"REPORT -> {path}", flush=True)
    return 0 if out["ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=float, default=12.0)
    ap.add_argument("--capital", type=float, default=5.0)
    ap.add_argument("--config", default="maker_demo_promo_pulse_micro5.json")
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
