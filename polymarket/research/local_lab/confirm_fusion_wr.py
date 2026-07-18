#!/usr/bin/env python3
"""Confirm fusion_follow_heavy WR>=70% @5 and @10 in parallel.

    python -m polymarket.research.local_lab.confirm_fusion_wr --sessions 6 --minutes 5
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
OUT = POLY / "data_local" / "local_lab" / "fusion_confirm"
BASE = POLY / "config" / "maker_demo_fusion_follow_heavy.json"


def _cfg(capital: float) -> Path:
    cfg = json.loads(BASE.read_text(encoding="utf-8"))
    cfg["initial_capital_usdc"] = float(capital)
    cfg["preserve_selectivity"] = True
    cfg = apply_live_clob_floors(cfg)
    cfg["quote_size_shares"] = 5
    cfg["max_quote_size_shares"] = 5
    cfg["max_inventory_shares"] = 5
    cfg["max_notional_per_side_usdc"] = 3.0
    cfg["max_inventory_usdc"] = 3.0
    cfg["demo_label"] = f"fusion_follow_heavy_c{int(capital)}"
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"cfg_c{int(capital)}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


async def run_cap(capital: float, sessions: int, minutes: float) -> dict:
    _nim_env()
    os.environ["NVIDIA_NIM_CONFIDENCE_MIN"] = "0.55"
    os.environ["BATCH_STOP_AFTER_STARVE_STREAK"] = "20"
    os.environ["BATCH_STOP_AFTER_LOSS_STREAK"] = "5"
    path = _cfg(capital)
    tag = f"confirm_c{int(capital)}"
    print(f"\n>>> CONFIRM START {tag} {sessions}x{minutes}m", flush=True)
    summary = await run_batch(
        strategy="maker_fusion",
        config=str(path),
        sessions=sessions,
        minutes=minutes,
        session_prefix=tag,
    )
    m = _metrics(summary)
    row = {"capital": capital, "cfg": str(path), **m}
    row["hit_wr70"] = bool(
        float(row.get("wr") or 0) >= 0.70 and int(row.get("sessions_with_fills") or 0) >= 2
    )
    print(
        f"<<< CONFIRM DONE {tag} WR={float(row.get('wr') or 0):.0%} "
        f"traded={row.get('sessions_with_fills')} total={float(row.get('total') or 0):+.2f} "
        f"{'PASS' if row['hit_wr70'] else 'FAIL'}",
        flush=True,
    )
    (OUT / f"partial_{tag}.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    return row


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    capitals = [float(x) for x in args.capitals.split(",") if x.strip()]
    rows = await asyncio.gather(
        *[run_cap(c, args.sessions, args.minutes) for c in capitals]
    )
    rows_l = list(rows)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "method": "fusion_follow_heavy",
        "strategy": "maker_fusion",
        "target": "WR>=0.70 @5 and @10 traded>=2",
        "rows": rows_l,
        "both_ready": all(r.get("hit_wr70") for r in rows_l),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"confirm_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "confirm_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    if report["both_ready"]:
        champ = json.loads(BASE.read_text(encoding="utf-8"))
        champ["demo_label"] = "grind_nim_best"
        champ["notes"] = (
            f"PROMOTED fusion_follow_heavy {stamp}: "
            + ", ".join(
                f"{int(r['capital'])}€ WR{float(r['wr']):.0%} "
                f"({r.get('sessions_with_fills')} traded, {float(r.get('total') or 0):+.2f})"
                for r in rows_l
            )
            + ". Strategy=maker_fusion. Paper feeds reales. No on-chain."
        )
        champ["_promo_strategy"] = "maker_fusion"
        # Write dedicated promo + update fusion champ; also snapshot as grind best notes
        (POLY / "config" / "maker_demo_fusion_follow_heavy.json").write_text(
            json.dumps({**champ, "demo_label": "fusion_follow_heavy"}, indent=2) + "\n",
            encoding="utf-8",
        )
        (POLY / "config" / "maker_demo_promo_fusion_follow_heavy.json").write_text(
            json.dumps(champ, indent=2) + "\n", encoding="utf-8"
        )
        # Keep grind_nim_best as paper champ pointer with fusion DNA + strategy hint
        (POLY / "config" / "maker_demo_grind_nim_best.json").write_text(
            json.dumps(champ, indent=2) + "\n", encoding="utf-8"
        )
        print("PROMOTED fusion_follow_heavy -> grind_nim_best (+ promo snapshot)", flush=True)

    print(f"REPORT -> {path}", flush=True)
    print("BOTH_READY:", report["both_ready"], flush=True)
    return 0 if report["both_ready"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capitals", default="5,10")
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--minutes", type=float, default=5.0)
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
