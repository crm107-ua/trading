#!/usr/bin/env python3
"""Batch paper sessions — win-rate on $100 demo (non-binding, local lab only)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from polymarket.research.local_lab.paper_maker import run_paper_session
from polymarket.research.local_lab.run_local_lab import resolve_config_path
from polymarket.src.ai.env_loader import load_repo_dotenv, require_nvidia_api_key

load_repo_dotenv()


async def run_batch(
    *,
    strategy: str,
    config: str,
    sessions: int,
    minutes: float,
) -> dict:
    require_nvidia_api_key()
    cfg_path = resolve_config_path(config)
    results: list[dict] = []
    for i in range(sessions):
        sid = f"batch_{i+1:02d}"
        print(f"\n=== session {i+1}/{sessions} ({minutes} min) ===", flush=True)
        rep = await run_paper_session(
            strategy_id=strategy,
            minutes=minutes,
            session_id=sid,
            config_path=cfg_path,
        )
        results.append(
            {
                "session_id": sid,
                "net": rep["net_session_usdc"],
                "fills": rep["fills"],
                "adverse_rate": rep["adverse_rate"],
                "quotes": rep["quotes_logged"],
            }
        )
        print(
            f"  net={rep['net_session_usdc']:+.2f} fills={rep['fills']} adverse={rep['adverse_rate']}",
            flush=True,
        )

    wins = sum(1 for r in results if r["net"] > 0)
    breakeven = sum(1 for r in results if r["net"] == 0)
    losses = sum(1 for r in results if r["net"] < 0)
    win_rate = wins / len(results) if results else 0.0
    summary = {
        "strategy": strategy,
        "config": str(cfg_path),
        "sessions": sessions,
        "minutes_each": minutes,
        "win_rate": round(win_rate, 4),
        "wins": wins,
        "breakeven": breakeven,
        "losses": losses,
        "avg_net_usdc": round(sum(r["net"] for r in results) / len(results), 4) if results else 0,
        "results": results,
        "verdict_binding": False,
        "warning": "Lab local — win_rate no garantiza PnL real",
    }
    out = Path(__file__).resolve().parents[2] / "data_local" / "local_lab" / "batch_eval_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", default="wide_spread_probe")
    p.add_argument("--config", default="polymarket/config/maker_demo_100_opt.json")
    p.add_argument("--sessions", type=int, default=8)
    p.add_argument("--minutes", type=float, default=5.0)
    args = p.parse_args()
    summary = asyncio.run(
        run_batch(
            strategy=args.strategy,
            config=args.config,
            sessions=args.sessions,
            minutes=args.minutes,
        )
    )
    print(json.dumps(summary, indent=2))
    target = 0.75
    if summary["win_rate"] >= target:
        print(f"\nOK: win_rate {summary['win_rate']*100:.1f}% >= {target*100:.0f}%", flush=True)
        return 0
    print(f"\nFAIL: win_rate {summary['win_rate']*100:.1f}% < {target*100:.0f}%", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
