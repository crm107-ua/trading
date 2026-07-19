#!/usr/bin/env python3
"""Paralelismo pro pulse@10: stagger + risk budget + WR decisivo + colisiones.

    python3 -m polymarket.research.local_lab.pro_parallel_pulse \
      --lines 4 --sessions 6 --minutes 5 --stagger-s 45
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.batch_paper_eval import run_batch
from polymarket.research.local_lab.desk_risk import (
    build_risk_budget,
    collision_rate,
    forecast_pnl,
    metrics_from_robust,
)
from polymarket.research.local_lab.go_live_gate import _robust_from_sessions
from polymarket.research.local_lab.iterate_grind_wr import _metrics, _nim_env
from polymarket.src.ai.env_loader import load_repo_dotenv, require_nvidia_api_key
from polymarket.web_lab.catalog import apply_live_clob_floors

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]


async def _run_line(
    *,
    label: str,
    strategy: str,
    cfg_name: str,
    capital: float,
    line_id: int,
    sessions: int,
    minutes: float,
    out: Path,
    sem: asyncio.Semaphore,
    stagger_s: float,
) -> dict:
    # Stagger deliberado: reduce colisión temporal en el mismo BTC 5m.
    if stagger_s > 0 and line_id > 1:
        delay = float(stagger_s) * (line_id - 1)
        print(f"STAGGER line={line_id} sleep={delay:.0f}s", flush=True)
        await asyncio.sleep(delay)
    async with sem:
        _nim_env()
        os.environ["NVIDIA_NIM_CONFIDENCE_MIN"] = "0.55"
        os.environ["BATCH_STOP_AFTER_STARVE_STREAK"] = "20"
        os.environ["BATCH_STOP_AFTER_LOSS_STREAK"] = "8"
        cfg = json.loads((POLY / "config" / cfg_name).read_text(encoding="utf-8"))
        cfg["initial_capital_usdc"] = float(capital)
        cfg["preserve_selectivity"] = True
        cfg["strategy_id"] = strategy
        cfg = apply_live_clob_floors(cfg)
        size = float(cfg.get("quote_size_shares", 5) or 5)
        size = max(1.0, min(size, float(cfg.get("max_quote_size_shares", size) or size)))
        cfg["quote_size_shares"] = size
        cfg["max_quote_size_shares"] = size
        cfg["max_inventory_shares"] = size
        cfg["demo_label"] = f"{label}_L{line_id}_c{int(capital)}"
        line_dir = out / f"line_{line_id:02d}"
        line_dir.mkdir(parents=True, exist_ok=True)
        path = line_dir / "cfg.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        tag = f"{label}_L{line_id}_c{int(capital)}"
        print(
            f"\n>>> PRO LINE START {tag} strat={strategy} {sessions}x{minutes}m",
            flush=True,
        )
        summary = await run_batch(
            strategy=strategy,
            config=str(path),
            sessions=sessions,
            minutes=minutes,
            session_prefix=tag,
        )
        m = _metrics(summary)
        # Market IDs de fills para colisión
        mids: list[str] = []
        base = POLY / "data_local" / "local_lab" / strategy
        for sdir in sorted(base.glob(f"session_{tag}_*")):
            fp = sdir / "fills.jsonl"
            if not fp.is_file():
                continue
            for line in fp.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mid = row.get("market_id")
                if mid:
                    mids.append(str(mid))
        wins = int(m.get("wins_traded") or 0)
        losses = int(m.get("losses_traded") or 0)
        decisive = wins + losses
        wr_dec = (wins / decisive) if decisive else 0.0
        row = {
            "label": label,
            "line_id": line_id,
            "strategy": strategy,
            "capital": capital,
            "cfg": str(path),
            "market_ids": mids,
            "wr_decisive": round(wr_dec, 4),
            "decisive": decisive,
            **m,
        }
        row["hit_wr70"] = bool(wr_dec >= 0.70 and decisive >= 2)
        print(
            f"<<< PRO LINE DONE {tag} WRd={wr_dec:.0%} "
            f"dec={decisive} total={float(row.get('total') or 0):+.2f} "
            f"{'PASS' if row['hit_wr70'] else 'FAIL'}",
            flush=True,
        )
        (line_dir / "partial.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        return row


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    out = POLY / "data_local" / "local_lab" / f"pro_parallel_{args.label}"
    out.mkdir(parents=True, exist_ok=True)
    budget = build_risk_budget(
        lines=int(args.lines),
        capital_per_line=float(args.capital),
        stagger_s=float(args.stagger_s),
        rho=float(args.rho),
    )
    print("RISK_BUDGET", json.dumps(budget.to_dict()), flush=True)
    sem = asyncio.Semaphore(max(1, int(args.parallel)))
    rows = list(
        await asyncio.gather(
            *[
                _run_line(
                    label=args.label,
                    strategy=args.strategy,
                    cfg_name=args.config,
                    capital=float(args.capital),
                    line_id=i + 1,
                    sessions=args.sessions,
                    minutes=args.minutes,
                    out=out,
                    sem=sem,
                    stagger_s=float(args.stagger_s),
                )
                for i in range(int(args.lines))
            ]
        )
    )
    wins = sum(int(r.get("wins_traded") or 0) for r in rows)
    losses = sum(int(r.get("losses_traded") or 0) for r in rows)
    traded = sum(int(r.get("sessions_with_fills") or 0) for r in rows)
    decisive = wins + losses
    total = sum(float(r.get("total") or 0) for r in rows)
    wr_traded = (wins / traded) if traded else 0.0
    wr_dec = (wins / decisive) if decisive else 0.0
    coll = collision_rate([list(r.get("market_ids") or []) for r in rows])
    robust = _robust_from_sessions(
        f"session_{args.label}_L*_c{int(args.capital)}_*",
        outlier_cap=0.35,
        max_age_hours=float(args.max_age_hours),
    )
    prox = metrics_from_robust(robust)
    fc = forecast_pnl(
        hours=1.0,
        lines=int(args.lines),
        wr=float(prox["wr"] or wr_dec),
        avg_win=float(prox["avg_win_usdc"]),
        avg_loss=float(prox["avg_loss_usdc"]),
        rho=float(args.rho),
        capital_scale=1.0,
    )
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "strategy": args.strategy,
        "config": args.config,
        "capital": float(args.capital),
        "lines": int(args.lines),
        "stagger_s": float(args.stagger_s),
        "risk_budget": budget.to_dict(),
        "rows": rows,
        "aggregate": {
            "total_pnl": round(total, 4),
            "wins_traded": wins,
            "losses_traded": losses,
            "sessions_with_fills": traded,
            "decisive": decisive,
            "aggregate_wr_traded": round(wr_traded, 4),
            "aggregate_wr_decisive": round(wr_dec, 4),
            "lines_pass_wr70": sum(1 for r in rows if r.get("hit_wr70")),
            "all_lines_pass": all(r.get("hit_wr70") for r in rows),
        },
        "collision": coll,
        "robust": robust,
        "forecast_1h": fc,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out / f"pro_parallel_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "pro_parallel_latest.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    agg = report["aggregate"]
    print(
        f"\nPRO AGG lines={args.lines} WRd={agg['aggregate_wr_decisive']:.0%} "
        f"dec={agg['decisive']} total={agg['total_pnl']:+.2f} "
        f"collision={coll['collision_rate']:.0%} "
        f"EV1h_corr={fc['pnl_corr_adjusted_usdc']:+.3f}",
        flush=True,
    )
    print(f"REPORT -> {path}", flush=True)
    ok = wr_dec >= 0.70 and decisive >= 4
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", default="pro_pulse_c10")
    ap.add_argument("--strategy", default="maker_fusion")
    ap.add_argument("--config", default="maker_demo_promo_pulse_c10.json")
    ap.add_argument("--capital", type=float, default=10.0)
    ap.add_argument("--lines", type=int, default=4)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--stagger-s", type=float, default=45.0)
    ap.add_argument("--rho", type=float, default=0.85)
    ap.add_argument("--max-age-hours", type=float, default=3.0)
    raise SystemExit(asyncio.run(async_main(ap.parse_args())))


if __name__ == "__main__":
    main()
