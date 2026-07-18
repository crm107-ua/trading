#!/usr/bin/env python3
"""Confirm one DNA at @5 and @10 until WR>=70% traded>=2 on BOTH.

    python -m polymarket.research.local_lab.confirm_dna_pair \
      --label fusion_follow_heavy --strategy maker_fusion \
      --config maker_demo_fusion_follow_heavy.json --sessions 6 --minutes 5
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


async def run_cap(
    *,
    label: str,
    strategy: str,
    cfg_name: str,
    capital: float,
    sessions: int,
    minutes: float,
    out: Path,
) -> dict:
    _nim_env()
    os.environ["NVIDIA_NIM_CONFIDENCE_MIN"] = "0.55"
    os.environ["BATCH_STOP_AFTER_STARVE_STREAK"] = "20"
    os.environ["BATCH_STOP_AFTER_LOSS_STREAK"] = "5"
    cfg = json.loads((POLY / "config" / cfg_name).read_text(encoding="utf-8"))
    cfg["initial_capital_usdc"] = float(capital)
    cfg["preserve_selectivity"] = True
    cfg = apply_live_clob_floors(cfg)
    cfg["quote_size_shares"] = 5
    cfg["max_quote_size_shares"] = 5
    cfg["max_inventory_shares"] = 5
    cfg["max_notional_per_side_usdc"] = 3.0
    cfg["max_inventory_usdc"] = 3.0
    cfg["demo_label"] = f"{label}_c{int(capital)}"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"cfg_{label}_c{int(capital)}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tag = f"{label}_c{int(capital)}"
    print(f"\n>>> PAIR CONFIRM START {tag} strat={strategy} {sessions}x{minutes}m", flush=True)
    summary = await run_batch(
        strategy=strategy,
        config=str(path),
        sessions=sessions,
        minutes=minutes,
        session_prefix=tag,
    )
    m = _metrics(summary)
    row = {"label": label, "strategy": strategy, "capital": capital, "cfg": str(path), **m}
    row["hit_wr70"] = bool(
        float(row.get("wr") or 0) >= 0.70 and int(row.get("sessions_with_fills") or 0) >= 2
    )
    print(
        f"<<< PAIR CONFIRM DONE {tag} WR={float(row.get('wr') or 0):.0%} "
        f"traded={row.get('sessions_with_fills')} total={float(row.get('total') or 0):+.2f} "
        f"{'PASS' if row['hit_wr70'] else 'FAIL'}",
        flush=True,
    )
    (out / f"partial_{tag}.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    return row


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    out = POLY / "data_local" / "local_lab" / f"confirm_{args.label}"
    capitals = [float(x) for x in args.capitals.split(",") if x.strip()]
    rows = list(
        await asyncio.gather(
            *[
                run_cap(
                    label=args.label,
                    strategy=args.strategy,
                    cfg_name=args.config,
                    capital=c,
                    sessions=args.sessions,
                    minutes=args.minutes,
                    out=out,
                )
                for c in capitals
            ]
        )
    )
    both = all(r.get("hit_wr70") for r in rows)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "strategy": args.strategy,
        "config": args.config,
        "rows": rows,
        "both_ready": both,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out / f"confirm_{stamp}.json"
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "confirm_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if both:
        champ = json.loads((POLY / "config" / args.config).read_text(encoding="utf-8"))
        champ["demo_label"] = args.label
        champ["notes"] = (
            f"CONFIRMED {args.label} {stamp}: "
            + ", ".join(
                f"{int(r['capital'])}€ WR{float(r['wr']):.0%} "
                f"traded={r.get('sessions_with_fills')} tot={float(r.get('total') or 0):+.2f}"
                for r in rows
            )
            + f". Strategy={args.strategy}. Paper feeds reales. No on-chain."
        )
        champ["_promo_strategy"] = args.strategy
        promo = POLY / "config" / f"maker_demo_promo_{args.label}.json"
        promo.write_text(json.dumps(champ, indent=2) + "\n", encoding="utf-8")
        (POLY / "config" / args.config).write_text(
            json.dumps(champ, indent=2) + "\n", encoding="utf-8"
        )
        print(f"PROMOTED {args.label} -> {promo}", flush=True)
    print(f"REPORT -> {path}", flush=True)
    print("BOTH_READY:", both, flush=True)
    return 0 if both else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--capitals", default="5,10")
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--minutes", type=float, default=5.0)
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
