#!/usr/bin/env python3
"""Dry-run live real @5 y @10 (CLOB/feeds reales, 0 órdenes on-chain).

Fuerza DRY_RUN=1 siempre. No toca .env. Al terminar deja el proceso SAFE
(ARMED=0) en os.environ.

    python3 -m polymarket.research.local_lab.run_live_dry_pair --minutes 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "live_dry_pair"


def _force_dry(*, max_capital: float) -> None:
    """ARMED temporal solo para esta prueba; DRY_RUN siempre 1."""
    os.environ["POLY_LIVE_ARMED"] = "1"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = str(float(max_capital))


def _force_safe() -> None:
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"


async def _one(*, label: str, config: str, minutes: float, session_id: str) -> dict:
    from polymarket.research.local_lab.live_maker import run_live_session

    path = POLY / "config" / config
    print(f"\n===== DRY LIVE START {label} cfg={config} {minutes}m =====", flush=True)
    report = await run_live_session(
        minutes=minutes,
        config_path=path,
        session_id=session_id,
    )
    row = {
        "label": label,
        "config": config,
        "session_id": session_id,
        "verdict": report.get("verdict"),
        "dry_run": report.get("dry_run"),
        "net_session_usdc": report.get("net_session_usdc"),
        "fills": report.get("fills"),
        "quotes_logged": report.get("quotes_logged"),
        "session_dir": report.get("session_dir"),
        "balance_end": report.get("bankroll_end_usdc"),
    }
    print(
        f"===== DRY LIVE DONE {label} verdict={row['verdict']} "
        f"fills={row['fills']} net={row['net_session_usdc']} =====",
        flush=True,
    )
    return row


async def async_main(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _force_dry(max_capital=max(10.0, float(args.max_capital)))

    from polymarket.src.execution.clob_live import ClobLiveClient, read_gates

    gates = read_gates()
    if not gates.dry_run:
        _force_safe()
        raise RuntimeError("ABORT: DRY_RUN no está activo — no se corre")
    if not gates.armed:
        raise RuntimeError("ABORT: no se pudo armar temporalmente para dry")

    cli = ClobLiveClient()
    cli.connect()
    bal = cli.balance_collateral_usdc()
    print(
        f"PREFLIGHT dry={gates.dry_run} armed={gates.armed} "
        f"max_cap={gates.max_capital_usdc} balance_pusd={bal:.4f}",
        flush=True,
    )

    rows: list[dict] = []
    try:
        if args.parallel:
            # return_exceptions: un blip CLOB no tumba el otro capital
            gathered = await asyncio.gather(
                _one(
                    label="dry_c5_flow",
                    config="maker_demo_promo_flow_c5.json",
                    minutes=float(args.minutes),
                    session_id=f"dry_c5_{stamp}",
                ),
                _one(
                    label="dry_c10_pulse",
                    config="maker_demo_promo_pulse_c10.json",
                    minutes=float(args.minutes),
                    session_id=f"dry_c10_{stamp}",
                ),
                return_exceptions=True,
            )
            for i, item in enumerate(gathered):
                if isinstance(item, Exception):
                    label = "dry_c5_flow" if i == 0 else "dry_c10_pulse"
                    print(f"DRY_FAIL {label}: {type(item).__name__}: {item}", flush=True)
                    rows.append(
                        {
                            "label": label,
                            "error": f"{type(item).__name__}: {item}",
                            "verdict": "ERROR",
                            "dry_run": True,
                            "fills": 0,
                            "net_session_usdc": 0.0,
                        }
                    )
                else:
                    rows.append(item)
        else:
            rows.append(
                await _one(
                    label="dry_c5_flow",
                    config="maker_demo_promo_flow_c5.json",
                    minutes=float(args.minutes),
                    session_id=f"dry_c5_{stamp}",
                )
            )
            rows.append(
                await _one(
                    label="dry_c10_pulse",
                    config="maker_demo_promo_pulse_c10.json",
                    minutes=float(args.minutes),
                    session_id=f"dry_c10_{stamp}",
                )
            )
    finally:
        _force_safe()
        print("SAFE restored: ARMED=0 DRY_RUN=1", flush=True)

    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "LIVE_DRY_RUN_REAL_CLOB",
        "money_real": False,
        "minutes": float(args.minutes),
        "balance_pusd_preflight": round(bal, 4),
        "rows": rows,
        "all_dry": all(bool(r.get("dry_run")) for r in rows),
        "any_real_orders": False,
    }
    path = OUT / f"dry_pair_{stamp}.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "dry_pair_latest.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    print(f"REPORT -> {path}", flush=True)
    ok = bool(summary["all_dry"]) and all(
        r.get("verdict") == "LIVE_DRY_RUN" for r in rows
    ) and len(rows) >= 2
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--max-capital", type=float, default=10.0)
    ap.add_argument(
        "--parallel",
        action="store_true",
        help="Corre @5 y @10 a la vez (ambos DRY)",
    )
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
