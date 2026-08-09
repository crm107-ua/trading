#!/usr/bin/env python3
"""Ejecuta Temperature Ladder vs Maker+CE y reporta PnL + winrate paper."""

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

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data_local" / "local_lab"


def _maker_net(report: dict[str, Any]) -> float:
    return float(report.get("net_session_usdc") or 0.0)


async def run_maker_rounds(
    *,
    config: Path,
    rounds: int,
    minutes: float,
) -> dict[str, Any]:
    sessions: list[dict[str, Any]] = []
    for i in range(rounds):
        sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + f"_r{i}"
        print(f"\n=== MAKER round {i+1}/{rounds} ({minutes} min) ===", flush=True)
        rep = await run_paper_session(
            "maker_16",
            minutes=minutes,
            config_path=config,
            session_id=sid,
        )
        net = _maker_net(rep)
        sessions.append(
            {
                "session_id": sid,
                "net_session_usdc": net,
                "fills": rep.get("fills"),
                "quotes_logged": rep.get("quotes_logged"),
                "nim_decisions_used": rep.get("nim_decisions_used"),
                "win": net > 1e-9,
                "session_dir": rep.get("session_dir"),
            }
        )
        print(
            f"maker round {i+1}: net={net:.4f} fills={rep.get('fills')} "
            f"nim={rep.get('nim_decisions_used')}",
            flush=True,
        )

    played = [s for s in sessions if int(s.get("fills") or 0) > 0]
    wins = sum(1 for s in played if s["win"])
    wr = (wins / len(played)) if played else None
    total_pnl = sum(float(s["net_session_usdc"]) for s in sessions)
    capital = float(json.loads(config.read_text(encoding="utf-8")).get("initial_capital_usdc", 10))
    return {
        "method": "maker_context_engineering",
        "rounds": rounds,
        "minutes_per_round": minutes,
        "capital_usdc": capital,
        "sessions": sessions,
        "rounds_with_fills": len(played),
        "wins": wins,
        "losses": len(played) - wins,
        "winrate": None if wr is None else round(wr, 4),
        "total_pnl_usdc": round(total_pnl, 4),
        "pnl_per_100_usdc": round((total_pnl / capital) * 100.0, 4) if capital else 0.0,
        "avg_pnl_per_round_usdc": round(total_pnl / max(rounds, 1), 4),
    }


def run_weather(config: Path) -> dict[str, Any]:
    print("\n=== WEATHER temperature ladder ===", flush=True)
    rep = run_weather_ladder_paper(config_path=config)
    taken = list(rep.get("taken") or [])
    wins = sum(1 for t in taken if float(t.get("pnl") or 0) > 1e-9)
    losses = sum(1 for t in taken if float(t.get("pnl") or 0) < -1e-9)
    flats = len(taken) - wins - losses
    wr = (wins / len(taken)) if taken else None
    pnl = float(rep.get("total_pnl_usdc") or 0.0)
    capital = float(rep.get("initial_capital_usdc") or 100.0)
    model_ev = 0.0
    for t in taken:
        try:
            model_ev += float(t.get("basket_ev") or 0) * float(t.get("spent") or 0)
        except (TypeError, ValueError):
            pass
    return {
        "method": "temperature_ladder",
        "capital_usdc": capital,
        "ladders_taken": len(taken),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "winrate": None if wr is None else round(wr, 4),
        "total_pnl_usdc": round(pnl, 4),
        "realized_pnl_usdc": rep.get("realized_pnl_usdc"),
        "open_mark_pnl_usdc": rep.get("open_mark_pnl_usdc"),
        "model_ev_dollar_proxy": round(model_ev, 4),
        "pnl_per_100_usdc": round((pnl / capital) * 100.0, 4) if capital else 0.0,
        "spent_usdc": rep.get("spent_usdc"),
        "session_id": rep.get("session_id"),
        "taken_slugs": [t.get("slug") for t in taken],
    }


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    load_repo_dotenv(override=True)
    # Keep hybrid from .env; only default if unset
    os.environ.setdefault("NVIDIA_NIM_MODE", "hybrid")
    os.environ.setdefault("NVIDIA_NIM_CONTEXT_ENGINEERING", "1")
    os.environ.setdefault("NVIDIA_NIM_GRIND", "1")

    weather_cfg = Path(args.weather_config)
    maker_cfg = Path(args.maker_config)
    weather = run_weather(weather_cfg)
    maker = await run_maker_rounds(
        config=maker_cfg,
        rounds=int(args.maker_rounds),
        minutes=float(args.maker_minutes),
    )

    # Rank by pnl_per_100 then winrate
    w_pnl = float(weather["pnl_per_100_usdc"])
    m_pnl = float(maker["pnl_per_100_usdc"])
    w_wr = weather["winrate"]
    m_wr = maker["winrate"]

    if w_pnl > m_pnl:
        winner_pnl = "temperature_ladder"
    elif m_pnl > w_pnl:
        winner_pnl = "maker_context_engineering"
    else:
        winner_pnl = "tie"

    if w_wr is None and m_wr is None:
        winner_wr = "n/a"
    elif w_wr is None:
        winner_wr = "maker_context_engineering"
    elif m_wr is None:
        winner_wr = "temperature_ladder"
    elif w_wr > m_wr:
        winner_wr = "temperature_ladder"
    elif m_wr > w_wr:
        winner_wr = "maker_context_engineering"
    else:
        winner_wr = "tie"

    out = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "nim_mode": os.environ.get("NVIDIA_NIM_MODE"),
        "context_engineering": os.environ.get("NVIDIA_NIM_CONTEXT_ENGINEERING"),
        "temperature_ladder": weather,
        "maker_context_engineering": maker,
        "winner_by_pnl_per_100": winner_pnl,
        "winner_by_winrate": winner_wr,
        "caveats": [
            "Weather winrate = ladders with mark-to-mid PnL>0 (open, pre-resolution).",
            "Maker winrate = rounds with fills and net_session>0.",
            "Mercados distintos (weather diario vs BTC-5m). No proyección anual.",
        ],
    }
    sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = OUT / f"race_paper_wr_{sid}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "race.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    out["race_dir"] = str(dest)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--maker-rounds", type=int, default=4)
    p.add_argument("--maker-minutes", type=float, default=6.0)
    p.add_argument(
        "--maker-config",
        default=str(ROOT / "config" / "maker_demo_grind_nim_v2.json"),
    )
    p.add_argument(
        "--weather-config",
        default=str(ROOT / "config" / "weather_ladder.json"),
    )
    args = p.parse_args()
    out = asyncio.run(main_async(args))
    # Compact print
    summary = {
        "winner_by_pnl_per_100": out["winner_by_pnl_per_100"],
        "winner_by_winrate": out["winner_by_winrate"],
        "temperature_ladder": {
            k: out["temperature_ladder"][k]
            for k in (
                "total_pnl_usdc",
                "pnl_per_100_usdc",
                "winrate",
                "wins",
                "losses",
                "ladders_taken",
                "model_ev_dollar_proxy",
            )
        },
        "maker_context_engineering": {
            k: out["maker_context_engineering"][k]
            for k in (
                "total_pnl_usdc",
                "pnl_per_100_usdc",
                "winrate",
                "wins",
                "losses",
                "rounds_with_fills",
                "rounds",
            )
        },
        "race_dir": out["race_dir"],
        "nim_mode": out["nim_mode"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
