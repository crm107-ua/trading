#!/usr/bin/env python3
"""
Live grid over real-feeds maker_edge configs. No synthetic fills.
Stops early if a config hits target win_rate with enough traded sessions.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from polymarket.research.local_lab.batch_paper_eval import run_batch
from polymarket.research.local_lab.edge_math import run_study
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab"
CFG_DIR = POLY / "config"


async def main() -> int:
    mc = run_study(OUT / "edge_study_mc.json")
    print(
        "MC best WR=",
        mc["best"]["win_rate"],
        "avg_pnl=",
        round(mc["best"]["avg_pnl"], 4),
        "params=",
        mc["best"]["params"],
        flush=True,
    )

    base = json.loads((CFG_DIR / "maker_demo_100_eur_edge.json").read_text(encoding="utf-8"))
    candidates = [
        {"name": "edge_v2_default", "overrides": {}},
        {"name": "edge_loose", "overrides": {"min_edge": 0.02, "min_z": 0.7, "min_take_profit": 0.008}},
        {
            "name": "edge_mc_tuned",
            "overrides": {
                "min_edge": 0.02,
                "half_spread": 0.01,
                "sigma_mid": 0.03,
                "min_z": 0.8,
                "quote_size_shares": 6,
                "kelly_sizing": False,
            },
        },
        {
            "name": "edge_high_bar",
            "overrides": {"min_edge": 0.04, "min_z": 1.2, "min_take_profit": 0.015, "quote_size_shares": 10},
        },
    ]

    results = []
    target = 0.75
    for c in candidates:
        cfg = dict(base)
        cfg.update(c["overrides"])
        cfg["demo_label"] = f"opt_{c['name']}"
        cfg["paper_touch_fill_every_n"] = 0
        cfg["paper_pnl_mode"] = ""
        tmp = OUT / f"cfg_{c['name']}.json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        print(f"\n===== LIVE {c['name']} (8x3min) =====", flush=True)
        summary = await run_batch(
            strategy="maker_edge",
            config=str(tmp),
            sessions=8,
            minutes=3.0,
        )
        summary["name"] = c["name"]
        results.append(summary)
        (OUT / f"opt_result_{c['name']}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(
            f"→ {c['name']}: win_rate={summary['win_rate']:.1%} "
            f"avg_net={summary['avg_net_usdc']:+.2f} traded={summary['sessions_with_fills']} "
            f"losses={summary['losses']}",
            flush=True,
        )
        if (
            summary["win_rate"] >= target
            and summary["sessions_with_fills"] >= 4
            and summary["avg_net_usdc"] > 0
            and summary["losses"] <= 1
        ):
            print(f"\nTARGET HIT with {c['name']}", flush=True)
            (OUT / "opt_best_real_feeds.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            # promote winning config
            (CFG_DIR / "maker_demo_100_eur_best.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            return 0

    results.sort(key=lambda r: (r.get("win_rate", 0), r.get("avg_net_usdc", 0)), reverse=True)
    (OUT / "opt_all_real_feeds.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    best = results[0]
    (OUT / "opt_best_real_feeds.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
    print("\nBest so far:", best["name"], "WR", best["win_rate"], "avg", best["avg_net_usdc"], flush=True)
    return 0 if best["win_rate"] >= target else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
