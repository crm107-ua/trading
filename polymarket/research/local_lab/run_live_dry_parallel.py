#!/usr/bin/env python3
"""Dry-run CLOB multi-línea pulse@10 (sin dinero real).

Fuerza ARMED=1 DRY_RUN=1, lanza N live_maker con stagger, restaura SAFE.

    python3 -m polymarket.research.local_lab.run_live_dry_parallel \
      --lines 2 --minutes 5 --stagger-s 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.desk_risk import build_risk_budget
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "live_dry_parallel"


def _force_dry(*, max_cap: float) -> dict[str, str]:
    prev = {
        "POLY_LIVE_ARMED": os.environ.get("POLY_LIVE_ARMED", "0"),
        "POLY_LIVE_DRY_RUN": os.environ.get("POLY_LIVE_DRY_RUN", "1"),
        "POLY_LIVE_MAX_CAPITAL_USDC": os.environ.get("POLY_LIVE_MAX_CAPITAL_USDC", "1.5"),
        "POLY_LIVE_DRY_SMOKE_POST": os.environ.get("POLY_LIVE_DRY_SMOKE_POST", "0"),
    }
    os.environ["POLY_LIVE_ARMED"] = "1"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = str(max(max_cap, 1.5))
    os.environ["POLY_LIVE_DRY_SMOKE_POST"] = "0"
    return prev


def _restore(prev: dict[str, str]) -> None:
    for k, v in prev.items():
        os.environ[k] = v
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    print("SAFE restored after dry parallel", flush=True)


async def _one(
    *,
    line_id: int,
    minutes: float,
    config: Path,
    stagger_s: float,
    strategy: str,
) -> dict:
    if stagger_s > 0 and line_id > 1:
        await asyncio.sleep(float(stagger_s) * (line_id - 1))
    from polymarket.research.local_lab.live_maker import run_live_session
    from polymarket.src.execution.clob_live import read_gates

    g = read_gates()
    if not g.dry_run:
        raise RuntimeError("ABORT: DRY_RUN no activo")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sid = f"dry_par_L{line_id}_{stamp}"
    print(f">>> DRY LINE {line_id} start {sid}", flush=True)
    report = await run_live_session(
        minutes=float(minutes),
        config_path=config,
        session_id=sid,
        strategy=strategy,
    )
    row = {
        "line_id": line_id,
        "ok": report.get("verdict") == "LIVE_DRY_RUN" and bool(report.get("dry_run")),
        "verdict": report.get("verdict"),
        "strategy_id": report.get("strategy_id"),
        "fills": report.get("fills"),
        "net": report.get("net_session_usdc"),
        "inventory_residual": report.get("inventory_residual"),
        "session_dir": report.get("session_dir"),
        "parity_ok": report.get("strategy_id") == strategy,
    }
    print(f"<<< DRY LINE {line_id} {row}", flush=True)
    return row


async def async_main(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cfg_path = POLY / "config" / args.config
    if not cfg_path.is_file():
        raise FileNotFoundError(cfg_path)
    cap = float(
        json.loads(cfg_path.read_text(encoding="utf-8")).get("initial_capital_usdc") or 1.5
    )
    budget = build_risk_budget(
        lines=int(args.lines),
        capital_per_line=cap,
        stagger_s=float(args.stagger_s),
    )
    prev = _force_dry(max_cap=max(cap, 10.0))
    try:
        from polymarket.src.execution.clob_live import ClobLiveClient, read_gates

        g = read_gates()
        bal_before = None
        try:
            cli = ClobLiveClient()
            cli.connect()
            bal_before = float(cli.balance_collateral_usdc())
        except Exception as e:
            print(f"BAL_BEFORE_ERR {type(e).__name__}: {e}", flush=True)
        rows = list(
            await asyncio.gather(
                *[
                    _one(
                        line_id=i + 1,
                        minutes=float(args.minutes),
                        config=cfg_path,
                        stagger_s=float(args.stagger_s),
                        strategy=args.strategy,
                    )
                    for i in range(int(args.lines))
                ]
            )
        )
        bal_after = None
        try:
            cli2 = ClobLiveClient()
            cli2.connect()
            bal_after = float(cli2.balance_collateral_usdc())
        except Exception as e:
            print(f"BAL_AFTER_ERR {type(e).__name__}: {e}", flush=True)
        all_ok = all(r.get("ok") for r in rows)
        parity_ok = all(r.get("parity_ok") for r in rows)
        residual_ok = all(abs(float(r.get("inventory_residual") or 0)) < 0.01 for r in rows)
        bal_ok = True
        if bal_before is not None and bal_after is not None:
            bal_ok = abs(bal_after - bal_before) < 0.02
        report = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "config": args.config,
            "strategy": args.strategy,
            "lines": int(args.lines),
            "minutes": float(args.minutes),
            "stagger_s": float(args.stagger_s),
            "risk_budget": budget.to_dict(),
            "gates": {"armed": g.armed, "dry_run": g.dry_run},
            "balance_before_pusd": bal_before,
            "balance_after_pusd": bal_after,
            "rows": rows,
            "all_ok": all_ok,
            "parity_ok": parity_ok,
            "residual_ok": residual_ok,
            "balance_intact": bal_ok,
            "any_real_orders": False,
            "verdict": (
                "DRY_PARALLEL_OK"
                if all_ok and parity_ok and residual_ok and bal_ok
                else "DRY_PARALLEL_FAIL"
            ),
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = OUT / f"dry_par_{stamp}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        (OUT / "dry_parallel_latest.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps({"verdict": report["verdict"], "rows": rows}, indent=2), flush=True)
        print(f"REPORT -> {path}", flush=True)
        return 0 if report["verdict"] == "DRY_PARALLEL_OK" else 1
    finally:
        _restore(prev)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="maker_demo_promo_pulse_c10_micro_live.json")
    ap.add_argument("--strategy", default="maker_fusion")
    ap.add_argument("--lines", type=int, default=2)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--stagger-s", type=float, default=30.0)
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
