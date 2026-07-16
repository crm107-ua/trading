#!/usr/bin/env python3
"""Batch paper sessions — win-rate on $100 demo (non-binding, local lab only)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
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
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    results: list[dict] = []
    # Tras N losses seguidas (sesiones con fills), para el batch: evita 5 rojas seguidas.
    streak_stop = int(os.getenv("BATCH_STOP_AFTER_LOSS_STREAK", "2") or 2)
    # N sesiones seguidas sin fills → parar (no quemar 60 min en wait_edge).
    starve_stop = int(os.getenv("BATCH_STOP_AFTER_STARVE_STREAK", "2") or 2)
    consec_losses = 0
    consec_starve = 0
    stopped_early = False
    stopped_early_starve = False
    for i in range(sessions):
        sid = f"v2_{stamp}_{i+1:02d}"
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
        n_fills = int(rep.get("fills") or 0)
        if n_fills <= 0:
            consec_starve += 1
            if starve_stop > 0 and consec_starve >= starve_stop:
                print(
                    f"\n*** BATCH STARVE KILL: {consec_starve} sesiones sin fills "
                    f"(limite={starve_stop}) — abrir edge/mid en siguiente trial ***",
                    flush=True,
                )
                stopped_early = True
                stopped_early_starve = True
                break
        else:
            consec_starve = 0
            if float(rep["net_session_usdc"]) < 0:
                consec_losses += 1
            elif float(rep["net_session_usdc"]) > 0:
                consec_losses = 0
            if streak_stop > 0 and consec_losses >= streak_stop:
                print(
                    f"\n*** BATCH STREAK KILL: {consec_losses} losses seguidas "
                    f"(limite={streak_stop}) — no seguir cavando ***",
                    flush=True,
                )
                stopped_early = True
                break

    wins = sum(1 for r in results if r["net"] > 0)
    breakeven = sum(1 for r in results if r["net"] == 0)
    losses = sum(1 for r in results if r["net"] < 0)
    with_fills = [r for r in results if r["fills"] > 0]
    wins_with_fills = sum(1 for r in with_fills if r["net"] > 0)
    # Primary metric: win rate on sessions that traded (empty = no signal)
    win_rate_traded = (wins_with_fills / len(with_fills)) if with_fills else 0.0
    no_loss_rate = (wins + breakeven) / len(results) if results else 0.0
    summary = {
        "strategy": strategy,
        "config": str(cfg_path),
        "sessions": sessions,
        "minutes_each": minutes,
        "win_rate": round(win_rate_traded, 4),
        "win_rate_definition": "net>0 among sessions with fills>0",
        "sessions_with_fills": len(with_fills),
        "wins": wins,
        "wins_with_fills": wins_with_fills,
        "breakeven": breakeven,
        "losses": losses,
        "no_loss_rate": round(no_loss_rate, 4),
        "avg_net_usdc": round(sum(r["net"] for r in results) / len(results), 4) if results else 0,
        "avg_net_traded_usdc": (
            round(sum(r["net"] for r in with_fills) / len(with_fills), 4) if with_fills else 0
        ),
        "results": results,
        "stopped_early_streak": stopped_early and not stopped_early_starve,
        "stopped_early_starve": stopped_early_starve,
        "loss_streak_limit": streak_stop,
        "starve_streak_limit": starve_stop,
        "verdict_binding": False,
        "warning": (
            "Lab local — win_rate no garantiza PnL real. "
            "locked_spread + paper_touch_fill son supuestos de paper, no edge on-chain."
        ),
    }
    out = Path(__file__).resolve().parents[2] / "data_local" / "local_lab" / "batch_eval_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", default="maker_16")
    p.add_argument("--config", default="polymarket/config/maker_demo_100_opt.json")
    p.add_argument("--sessions", type=int, default=8)
    p.add_argument("--minutes", type=float, default=4.0)
    p.add_argument("--target", type=float, default=0.75)
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
    target = args.target
    traded = summary["sessions_with_fills"]
    if traded < max(3, args.sessions // 3):
        print(
            f"\nFAIL: too few traded sessions ({traded}); need fills to measure win_rate",
            flush=True,
        )
        return 1
    if summary["win_rate"] >= target and summary["losses"] == 0:
        print(
            f"\nOK: win_rate {summary['win_rate']*100:.1f}% >= {target*100:.0f}% "
            f"(traded={traded}, losses={summary['losses']})",
            flush=True,
        )
        return 0
    if summary["win_rate"] >= target:
        print(
            f"\nOK: win_rate {summary['win_rate']*100:.1f}% >= {target*100:.0f}% "
            f"(traded={traded}; losses={summary['losses']} overall)",
            flush=True,
        )
        return 0
    print(f"\nFAIL: win_rate {summary['win_rate']*100:.1f}% < {target*100:.0f}%", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
