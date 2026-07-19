#!/usr/bin/env python3
"""Caza fusiones solo @10€ hasta WR>=70% traded>=2.

    python3 -m polymarket.research.local_lab.hunt_c10_fusions --sessions 6 --minutes 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.batch_paper_eval import run_batch
from polymarket.research.local_lab.iterate_grind_wr import _metrics, _nim_env
from polymarket.src.ai.env_loader import load_repo_dotenv, require_nvidia_api_key
from polymarket.web_lab.catalog import apply_live_clob_floors

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "hunt_c10_fusions"

DNA: list[tuple[str, str, str]] = [
    ("fusion_c10_bank", "maker_fusion", "maker_demo_fusion_c10_bank.json"),
    ("fusion_c10_pulse", "maker_fusion", "maker_demo_fusion_c10_pulse.json"),
    ("fusion_c10_edge", "maker_fusion", "maker_demo_fusion_c10_edge.json"),
    ("fusion_c10_flowv6", "maker_fusion", "maker_demo_fusion_c10_flowv6.json"),
]


async def _run_one(
    *,
    label: str,
    strategy: str,
    cfg_name: str,
    sessions: int,
    minutes: float,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    async with sem:
        _nim_env()
        os.environ["NVIDIA_NIM_CONFIDENCE_MIN"] = "0.55"
        os.environ["BATCH_STOP_AFTER_STARVE_STREAK"] = "16"
        os.environ["BATCH_STOP_AFTER_LOSS_STREAK"] = "5"
        cfg = json.loads((POLY / "config" / cfg_name).read_text(encoding="utf-8"))
        cfg["initial_capital_usdc"] = 10.0
        cfg["preserve_selectivity"] = True
        cfg = apply_live_clob_floors(cfg)
        size = float(cfg.get("quote_size_shares", 5) or 5)
        size = max(1.0, min(size, float(cfg.get("max_quote_size_shares", size) or size)))
        # CLOB floor may bump to 5; keep DNA intent when possible
        cfg["quote_size_shares"] = size
        cfg["max_quote_size_shares"] = size
        cfg["max_inventory_shares"] = size
        cfg["demo_label"] = f"{label}_c10"
        d = OUT / label
        d.mkdir(parents=True, exist_ok=True)
        path = d / "cfg.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"\n>>> C10 HUNT START {label} {sessions}x{minutes}m", flush=True)
        summary = await run_batch(
            strategy=strategy,
            config=str(path),
            sessions=sessions,
            minutes=minutes,
            session_prefix=f"{label}_c10",
        )
        m = _metrics(summary)
        row = {"label": label, "strategy": strategy, "capital": 10.0, "cfg": str(path), **m}
        row["hit_wr70"] = bool(
            float(row.get("wr") or 0) >= 0.70 and int(row.get("sessions_with_fills") or 0) >= 2
        )
        print(
            f"<<< C10 HUNT DONE {label} WR={float(row.get('wr') or 0):.0%} "
            f"traded={row.get('sessions_with_fills')} tot={float(row.get('total') or 0):+.2f} "
            f"{'PASS' if row['hit_wr70'] else 'FAIL'}",
            flush=True,
        )
        (d / "partial.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        return row


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = {x.strip() for x in args.labels.split(",") if x.strip()} if args.labels else None
    dna = [d for d in DNA if (wanted is None or d[0] in wanted)]
    sem = asyncio.Semaphore(max(1, int(args.parallel)))
    rows = list(
        await asyncio.gather(
            *[
                _run_one(
                    label=lab,
                    strategy=strat,
                    cfg_name=cfg,
                    sessions=args.sessions,
                    minutes=args.minutes,
                    sem=sem,
                )
                for lab, strat, cfg in dna
            ]
        )
    )
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            1 if r.get("hit_wr70") else 0,
            float(r.get("wr") or 0),
            float(r.get("total") or 0),
            int(r.get("sessions_with_fills") or 0),
        ),
        reverse=True,
    )
    best = rows_sorted[0] if rows_sorted else None
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "capital": 10.0,
        "rows": rows_sorted,
        "best": best,
        "any_pass": bool(best and best.get("hit_wr70")),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"hunt_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "hunt_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if best and best.get("hit_wr70"):
        src = POLY / "config" / next(c for l, _s, c in dna if l == best["label"])
        champ = json.loads(src.read_text(encoding="utf-8"))
        champ["demo_label"] = best["label"]
        champ["notes"] = (
            f"C10 CHAMP {stamp}: WR{float(best['wr']):.0%} "
            f"traded={best.get('sessions_with_fills')} tot={float(best.get('total') or 0):+.2f}"
        )
        promo = POLY / "config" / "maker_demo_promo_fusion_c10.json"
        promo.write_text(json.dumps(champ, indent=2) + "\n", encoding="utf-8")
        print(f"PROMO -> {promo}", flush=True)
    print(f"REPORT -> {path}", flush=True)
    print(
        f"BEST: {best['label'] if best else None} "
        f"WR={float(best.get('wr') or 0):.0%} traded={best.get('sessions_with_fills')} "
        f"tot={float(best.get('total') or 0):+.2f} PASS={bool(best and best.get('hit_wr70'))}",
        flush=True,
    )
    return 0 if report["any_pass"] else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--labels", default="", help="comma subset of DNA labels")
    raise SystemExit(asyncio.run(async_main(ap.parse_args())))


if __name__ == "__main__":
    main()
