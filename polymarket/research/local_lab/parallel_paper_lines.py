#!/usr/bin/env python3
"""Paraleliza N líneas paper del mismo DNA y acumula PnL/WR.

No hace promo automática (evita falsos BOTH_READY por capitals repetidos).

    python3 -m polymarket.research.local_lab.parallel_paper_lines \
      --label promo_flow_c5 --strategy maker_fusion \
      --config maker_demo_promo_flow_c5.json \
      --capital 5 --lines 4 --sessions 6 --minutes 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.batch_paper_eval import run_batch
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
    stagger_s: float = 0.0,
) -> dict:
    if stagger_s > 0 and line_id > 1:
        await asyncio.sleep(float(stagger_s) * (line_id - 1))
    async with sem:
        _nim_env()
        os.environ["NVIDIA_NIM_CONFIDENCE_MIN"] = "0.55"
        os.environ["BATCH_STOP_AFTER_STARVE_STREAK"] = "20"
        os.environ["BATCH_STOP_AFTER_LOSS_STREAK"] = "8"
        cfg = json.loads((POLY / "config" / cfg_name).read_text(encoding="utf-8"))
        cfg["initial_capital_usdc"] = float(capital)
        cfg["preserve_selectivity"] = True
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
            f"\n>>> LINE START {tag} strat={strategy} {sessions}x{minutes}m",
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
        row = {
            "label": label,
            "line_id": line_id,
            "strategy": strategy,
            "capital": capital,
            "cfg": str(path),
            **m,
        }
        row["hit_wr70"] = bool(
            float(row.get("wr") or 0) >= 0.70
            and int(row.get("sessions_with_fills") or 0) >= 2
        )
        print(
            f"<<< LINE DONE {tag} WR={float(row.get('wr') or 0):.0%} "
            f"traded={row.get('sessions_with_fills')} total={float(row.get('total') or 0):+.2f} "
            f"{'PASS' if row['hit_wr70'] else 'FAIL'}",
            flush=True,
        )
        (line_dir / "partial.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        return row


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    out = POLY / "data_local" / "local_lab" / f"parallel_{args.label}"
    out.mkdir(parents=True, exist_ok=True)
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
    traded = sum(int(r.get("sessions_with_fills") or 0) for r in rows)
    losses = sum(int(r.get("losses_traded") or 0) for r in rows)
    total = sum(float(r.get("total") or 0) for r in rows)
    decisive = wins + losses
    agg_wr = (wins / traded) if traded else 0.0
    agg_wr_dec = (wins / decisive) if decisive else 0.0
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "strategy": args.strategy,
        "config": args.config,
        "capital": float(args.capital),
        "lines": int(args.lines),
        "stagger_s": float(args.stagger_s),
        "sessions_per_line": args.sessions,
        "minutes": args.minutes,
        "rows": rows,
        "aggregate": {
            "total_pnl": round(total, 4),
            "wins_traded": wins,
            "losses_traded": losses,
            "sessions_with_fills": traded,
            "decisive": decisive,
            "aggregate_wr": round(agg_wr, 4),
            "aggregate_wr_decisive": round(agg_wr_dec, 4),
            "lines_pass_wr70": sum(1 for r in rows if r.get("hit_wr70")),
            "all_lines_pass": all(r.get("hit_wr70") for r in rows),
        },
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out / f"parallel_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "parallel_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    agg = report["aggregate"]
    print(
        f"\nAGGREGATE lines={args.lines} WR={agg['aggregate_wr']:.0%} "
        f"WRd={agg['aggregate_wr_decisive']:.0%} "
        f"traded={agg['sessions_with_fills']} total={agg['total_pnl']:+.2f} "
        f"pass_lines={agg['lines_pass_wr70']}/{args.lines}",
        flush=True,
    )
    print(f"REPORT -> {path}", flush=True)
    return 0 if agg["aggregate_wr_decisive"] >= 0.70 and decisive >= 2 else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", required=True)
    ap.add_argument("--strategy", default="maker_fusion")
    ap.add_argument("--config", required=True)
    ap.add_argument("--capital", type=float, default=5.0)
    ap.add_argument("--lines", type=int, default=4)
    ap.add_argument("--parallel", type=int, default=4, help="max concurrent lines")
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument(
        "--stagger-s",
        type=float,
        default=0.0,
        help="delay entre líneas (s) para reducir colisión mismo mercado",
    )
    raise SystemExit(asyncio.run(async_main(ap.parse_args())))


if __name__ == "__main__":
    main()
