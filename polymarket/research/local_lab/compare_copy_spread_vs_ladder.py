#!/usr/bin/env python3
"""
Head-to-head: viral micro-spread/copy sleeve vs weather ladder champion.

  python -m polymarket.research.local_lab.compare_copy_spread_vs_ladder
  python -m polymarket.research.local_lab.compare_copy_spread_vs_ladder --spread-rounds 6 --minutes 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.paper_maker import run_paper_session
from polymarket.research.local_lab.weather_ladder_paper import run_weather_ladder_paper
from polymarket.src.ai.env_loader import load_repo_dotenv

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "copy_research"
LADDER = POLY / "config" / "weather_ladder_champion_v2.json"
SPREAD = POLY / "config" / "maker_demo_copy_micro_spread.json"
GRIND = POLY / "config" / "maker_demo_grind_nim_best.json"


async def _run_spread(rounds: int, minutes: float, cfg: Path, strategy: str) -> dict[str, Any]:
    sessions = []
    for i in range(rounds):
        sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + f"_{strategy}_{i}"
        rep = await run_paper_session(strategy, minutes=minutes, config_path=cfg, session_id=sid)
        net = float(rep.get("net_session_usdc") or 0)
        fills = int(rep.get("fills") or 0)
        sessions.append({"net": net, "fills": fills, "win": net > 1e-9, "session_id": sid})
        print(f"{strategy} {i+1}/{rounds}: net={net:.4f} fills={fills}", flush=True)
    played = [s for s in sessions if s["fills"] > 0]
    wins = sum(1 for s in played if s["win"])
    pnl = sum(s["net"] for s in sessions)
    return {
        "strategy": strategy,
        "pnl": round(pnl, 4),
        "played": len(played),
        "wins": wins,
        "winrate": round(wins / len(played), 4) if played else None,
        "sessions": sessions,
    }


def main() -> int:
    load_repo_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--spread-rounds", type=int, default=5)
    p.add_argument("--minutes", type=float, default=4.0)
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    print("=== LADDER champion (resolved scorecard) ===", flush=True)
    ladder_rep = run_weather_ladder_paper(config_path=LADDER)
    ladder = {
        "strategy": "weather_ladder_champion_v3",
        "pnl": float(ladder_rep.get("scorecard_pnl_usdc") or 0),
        "winrate": ladder_rep.get("winrate"),
        "n": int(ladder_rep.get("resolved_taken") or 0),
        "wins": int(ladder_rep.get("wins") or 0),
        "session_id": ladder_rep.get("session_id"),
    }
    print(f"ladder pnl={ladder['pnl']} wr={ladder['winrate']} n={ladder['n']}", flush=True)

    print("=== MICRO-SPREAD follow (viral 0.48→0.52 style) ===", flush=True)
    spread = asyncio.run(
        _run_spread(int(args.spread_rounds), float(args.minutes), SPREAD, "maker_follow")
    )

    print("=== GRIND_NIM_BEST control sleeve ===", flush=True)
    grind = asyncio.run(
        _run_spread(max(3, int(args.spread_rounds) - 1), float(args.minutes), GRIND, "maker_edge")
    )

    # Winner by PnL then WR (research scorecard for ladder vs paper micro)
    ranked = sorted(
        [
            {"name": "ladder", **ladder},
            {"name": "micro_spread", **spread},
            {"name": "grind_nim", **grind},
        ],
        key=lambda r: (float(r.get("pnl") or -1e9), float(r.get("winrate") or 0)),
        reverse=True,
    )
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "ladder": ladder,
        "micro_spread": spread,
        "grind_nim": grind,
        "ranking": [r["name"] for r in ranked],
        "winner": ranked[0]["name"],
        "verdict": (
            "LADDER_STILL_BEST"
            if ranked[0]["name"] == "ladder"
            else "MICRO_SPREAD_COMPETITIVE"
            if ranked[0]["name"] == "micro_spread" and float(spread.get("pnl") or 0) > 0
            else "MIXED"
        ),
        "notes": [
            "Viral 'never lose wallets / curve only up' is not empirically supported.",
            "Micro-spread sleeve is maker_follow paper with 0.52/0.48 bands.",
            "Ladder PnL is resolved weather scorecard (same capital class, different horizon).",
        ],
    }
    path = OUT / f"compare_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("winner", "verdict", "ladder", "micro_spread", "grind_nim", "ranking")}, indent=2))
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
