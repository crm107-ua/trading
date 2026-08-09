#!/usr/bin/env python3
"""
Paper horse-race: Temperature Ladder (weather) vs Maker+ContextEngineering (BTC-5m).

Same starting capital lens; different markets/time microstructure — report is honest
about that. Outputs a side-by-side JSON under data_local/local_lab/compare_*.

  NVIDIA_NIM_MODE=fast python -m polymarket.research.local_lab.compare_ladder_vs_maker_paper --maker-minutes 3
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

ROOT = Path(__file__).resolve().parents[2]
OUT_BASE = ROOT / "data_local" / "local_lab"


def _maker_pnl(report: dict[str, Any]) -> float:
    for key in ("net_session_usdc", "net_pnl_usdc", "session_pnl_usdc", "pnl_usdc"):
        if key in report and report[key] is not None:
            try:
                return float(report[key])
            except (TypeError, ValueError):
                pass
    bank = report.get("bankroll_end_usdc")
    init = report.get("demo_capital_usdc")
    if bank is not None and init is not None:
        return float(bank) - float(init)
    return 0.0


async def run_compare(*, maker_minutes: float, maker_config: Path, weather_config: Path) -> dict[str, Any]:
    load_repo_dotenv()
    os.environ.setdefault("NVIDIA_NIM_MODE", "fast")
    os.environ.setdefault("NVIDIA_NIM_CONTEXT_ENGINEERING", "1")

    weather = run_weather_ladder_paper(config_path=weather_config)
    maker = await run_paper_session(
        "maker_16",
        minutes=maker_minutes,
        config_path=maker_config,
        session_id=f"cmp_{weather['session_id']}",
    )

    w_pnl = float(weather.get("total_pnl_usdc") or 0.0)
    m_pnl = _maker_pnl(maker)
    w_cap = float(weather.get("initial_capital_usdc") or 100.0)
    m_cap = float(maker.get("demo_capital_usdc") or 10.0)
    try:
        m_cap = float(
            json.loads(maker_config.read_text(encoding="utf-8")).get("initial_capital_usdc", m_cap)
        )
    except Exception:
        pass

    model_ev = 0.0
    for row in weather.get("taken") or []:
        try:
            model_ev += float(row.get("basket_ev") or 0.0) * float(row.get("spent") or 0.0)
        except (TypeError, ValueError):
            continue

    # Normalize to PnL per $100 capital for a rough apples-to-oranges lens
    w_per_100 = (w_pnl / w_cap) * 100.0 if w_cap else 0.0
    m_per_100 = (m_pnl / m_cap) * 100.0 if m_cap else 0.0

    if w_per_100 > m_per_100:
        winner = "temperature_ladder"
    elif m_per_100 > w_per_100:
        winner = "maker_context_engineering"
    else:
        winner = "tie"

    out = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "winner_by_pnl_per_100": winner,
        "temperature_ladder": {
            "pnl_usdc": w_pnl,
            "realized_pnl_usdc": weather.get("realized_pnl_usdc"),
            "open_mark_pnl_usdc": weather.get("open_mark_pnl_usdc"),
            "model_ev_dollar_proxy": round(model_ev, 4),
            "capital_usdc": w_cap,
            "pnl_per_100_usdc": round(w_per_100, 4),
            "ladders_taken": weather.get("ladders_taken"),
            "session_id": weather.get("session_id"),
            "spent_usdc": weather.get("spent_usdc"),
        },
        "maker_context_engineering": {
            "pnl_usdc": round(m_pnl, 4),
            "capital_usdc": m_cap,
            "pnl_per_100_usdc": round(m_per_100, 4),
            "fills": maker.get("fills"),
            "quotes_logged": maker.get("quotes_logged"),
            "minutes": maker_minutes,
            "demo_label": maker.get("demo_label"),
            "nim_mode": os.environ.get("NVIDIA_NIM_MODE"),
            "context_engineering": os.environ.get("NVIDIA_NIM_CONTEXT_ENGINEERING"),
            "session_dir": maker.get("out_dir") or maker.get("session_dir"),
        },
        "caveats": [
            "Different markets (weather daily vs BTC-5m microstructure).",
            "Weather open legs marked to mid after buying ask → immediate spread drag.",
            "Maker grind-ultra may post 0 fills in short windows (selective mids).",
            "Not an annual projection. Lab can only kill ideas, not approve them.",
        ],
    }

    sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_BASE / f"compare_ladder_vs_maker_{sid}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "compare.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (out_dir / "weather_report.json").write_text(json.dumps(weather, indent=2), encoding="utf-8")
    (out_dir / "maker_report.json").write_text(json.dumps(maker, indent=2), encoding="utf-8")
    out["compare_dir"] = str(out_dir)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--maker-minutes", type=float, default=3.0)
    p.add_argument(
        "--maker-config",
        default=str(ROOT / "config" / "maker_demo_grind_nim_v2.json"),
    )
    p.add_argument(
        "--weather-config",
        default=str(ROOT / "config" / "weather_ladder.json"),
    )
    args = p.parse_args()
    out = asyncio.run(
        run_compare(
            maker_minutes=args.maker_minutes,
            maker_config=Path(args.maker_config),
            weather_config=Path(args.weather_config),
        )
    )
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print("WINNER:", out["winner_by_pnl_per_100"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
