#!/usr/bin/env python3
"""
Winning desk — capital allocation across researched edges.

Stack (paper only):
  1. Temperature Ladder champion (HK/SG/SH/Beijing multi-sleeve)
  2. Idle capital: grind_nim_best OR micro_spread (0.48/0.52 follow bands)

Research basis:
  - SurferX ladder math + underdispersion / cheap neighborhood
  - Multi-day resolved sweep: SG WR100%, SG+SH WR80% (+$157 / 10 trades)
  - grind_nim_best lab champion (WR≥75% historical paper)

  python -m polymarket.research.local_lab.winning_desk
  python -m polymarket.research.local_lab.winning_desk --maker-rounds 4 --maker-minutes 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.paper_maker import run_paper_session
from polymarket.research.local_lab.weather_ladder_paper import run_weather_ladder_paper
from polymarket.src.ai.env_loader import load_repo_dotenv

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "winning_desk"
LADDER_CFG = POLY / "config" / "weather_ladder_final_longterm.json"
MAKER_CFG = POLY / "config" / "maker_demo_grind_nim_best.json"
SPREAD_CFG = POLY / "config" / "maker_demo_copy_micro_spread.json"
IDLE_SLEEVES = {
    "grind": ("maker_edge", MAKER_CFG),
    "micro_spread": ("maker_follow", SPREAD_CFG),
}


def _ladder_stats(rep: dict[str, Any]) -> dict[str, Any]:
    taken = list(rep.get("taken") or [])
    resolved = [t for t in taken if t.get("resolved")]
    wins = sum(1 for t in resolved if float(t.get("pnl") or 0) > 1e-9)
    return {
        "pnl": float(rep.get("scorecard_pnl_usdc") or rep.get("realized_pnl_usdc") or 0),
        "total_pnl": float(rep.get("total_pnl_usdc") or 0),
        "wins": wins,
        "n": len(resolved),
        "open_n": len(taken) - len(resolved),
        "winrate": (wins / len(resolved)) if resolved else None,
        "spent": float(rep.get("spent_usdc") or 0),
        "session_id": rep.get("session_id"),
        "slugs": [t.get("slug") for t in taken],
        "sleeves": sorted({t.get("sleeve") for t in taken if t.get("sleeve")}),
    }


async def _maker_sleeve(rounds: int, minutes: float, *, sleeve: str = "grind") -> dict[str, Any]:
    strategy_name, cfg_path = IDLE_SLEEVES.get(sleeve, IDLE_SLEEVES["grind"])
    sessions: list[dict[str, Any]] = []
    for i in range(rounds):
        sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + f"_wd{i}"
        rep = await run_paper_session(
            strategy_name,
            minutes=minutes,
            config_path=cfg_path,
            session_id=sid,
        )
        net = float(rep.get("net_session_usdc") or 0)
        sessions.append(
            {
                "net": net,
                "fills": rep.get("fills"),
                "nim": rep.get("nim_decisions_used"),
                "win": net > 1e-9,
                "session_dir": rep.get("session_dir"),
            }
        )
        print(f"maker sleeve {i+1}/{rounds}: net={net:.3f} fills={rep.get('fills')}", flush=True)
    played = [s for s in sessions if int(s.get("fills") or 0) > 0]
    wins = sum(1 for s in played if s["win"])
    pnl = sum(float(s["net"]) for s in sessions)
    return {
        "pnl": round(pnl, 4),
        "wins": wins,
        "played": len(played),
        "winrate": (wins / len(played)) if played else None,
        "sessions": sessions,
    }


async def run_desk(*, maker_rounds: int, maker_minutes: float, idle_sleeve: str = "grind") -> dict[str, Any]:
    load_repo_dotenv(override=True)
    os.environ.setdefault("NVIDIA_NIM_MODE", "hybrid")
    os.environ.setdefault("NVIDIA_NIM_GRIND", "1")
    os.environ.setdefault("NVIDIA_NIM_PROFIT_ASSIST", "1")
    os.environ.setdefault("NVIDIA_NIM_CONTEXT_ENGINEERING", "1")
    os.environ.setdefault("NVIDIA_NIM_MODEL", "nvidia/nemotron-mini-4b-instruct")

    OUT.mkdir(parents=True, exist_ok=True)
    print("=== LADDER champion sleeve (SG/Shanghai) ===", flush=True)
    ladder_rep = run_weather_ladder_paper(config_path=LADDER_CFG)
    ladder = _ladder_stats(ladder_rep)

    # Idle capital after ladder spend → maker sleeve (micro)
    ladder_cfg = json.loads(LADDER_CFG.read_text(encoding="utf-8"))
    bank = float(ladder_cfg.get("initial_capital_usdc", 100))
    idle = bank - float(ladder["spent"])
    run_maker = idle >= 8.0 and maker_rounds > 0
    maker: dict[str, Any]
    if run_maker:
        print(f"=== MAKER idle sleeve={idle_sleeve} (idle≈{idle:.1f}) ===", flush=True)
        maker = await _maker_sleeve(maker_rounds, maker_minutes, sleeve=idle_sleeve)
        maker["idle_sleeve"] = idle_sleeve
    else:
        maker = {"pnl": 0.0, "wins": 0, "played": 0, "winrate": None, "sessions": [], "skipped": "no_idle_or_rounds0"}

    total = float(ladder["pnl"]) + float(maker["pnl"])
    # Combined WR: ladder trades + maker played rounds
    lw, ln = int(ladder["wins"]), int(ladder["n"])
    mw, mn = int(maker["wins"]), int(maker["played"])
    comb_n = ln + mn
    comb_w = lw + mw
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": "winning_desk_v2_multi_sleeve",
        "thesis": (
            "Primary: multi-sleeve Temperature Ladder — "
            "core SG/SH/HK (WR100%) + Beijing bias+1.0 (WR≈88%); union WR≈93% / +$610 research. "
            "Secondary: grind_nim_best maker only on idle capital."
        ),
        "ladder": ladder,
        "maker": maker,
        "combined_pnl_usdc": round(total, 4),
        "combined_winrate": round(comb_w / comb_n, 4) if comb_n else None,
        "combined_wins": comb_w,
        "combined_trades": comb_n,
        "verdict": (
            "STRONG"
            if float(ladder["pnl"]) > 0 and (ln == 0 or (lw / ln) >= 0.7)
            else "MIXED"
            if total > 0
            else "WEAK"
        ),
        "guards": [
            "Paper only — not on-chain approval",
            "Ladder edge realized at resolution / resolved replay",
            "Exclude Seoul (0% WR in sweep)",
            "POLY_LIVE_ARMED must stay 0 until separate go-live gate",
        ],
    }
    sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"desk_{sid}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "ladder_report.json").write_text(json.dumps(ladder_rep, indent=2), encoding="utf-8")
    report["path"] = str(path)
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--maker-rounds", type=int, default=3)
    p.add_argument("--maker-minutes", type=float, default=5.0)
    p.add_argument("--idle-sleeve", choices=sorted(IDLE_SLEEVES), default="grind")
    p.add_argument(
        "--micro-dry",
        action="store_true",
        help="Also run Temperature Ladder CLOB micro dry-run (DRY_RUN=1, restores SAFE)",
    )
    args = p.parse_args()
    rep = asyncio.run(
        run_desk(
            maker_rounds=args.maker_rounds,
            maker_minutes=args.maker_minutes,
            idle_sleeve=args.idle_sleeve,
        )
    )
    if args.micro_dry:
        from polymarket.research.local_lab.weather_ladder_live import run_session

        dry = run_session(
            config_path=POLY / "config" / "weather_ladder_micro_dry.json",
            mode="both",
        )
        rep["ladder_micro_dry"] = {
            "overall_verdict": dry.get("overall_verdict"),
            "session_id": dry.get("session_id"),
            "safe_after": dry.get("safe_after"),
        }
    print(json.dumps({k: rep[k] for k in rep if k not in ("ladder", "maker") or True}, indent=2, default=str)[:4000])
    print(
        f"\nDESK PnL={rep['combined_pnl_usdc']} WR={rep['combined_winrate']} "
        f"verdict={rep['verdict']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
