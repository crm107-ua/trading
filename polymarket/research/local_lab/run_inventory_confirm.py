#!/usr/bin/env python3
import asyncio
import json
from pathlib import Path

from polymarket.research.local_lab.batch_paper_eval import run_batch
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

CFG = Path(__file__).resolve().parents[2] / "config" / "maker_demo_100_usd_inventory.json"


async def main() -> None:
    summary = await run_batch(
        strategy="maker_edge",
        config=str(CFG),
        sessions=6,
        minutes=3.0,
    )
    print(
        f"CONFIRM WR={summary['win_rate']:.1%} avg={summary['avg_net_usdc']:+.2f} "
        f"losses={summary['losses']} traded={summary['sessions_with_fills']}",
        flush=True,
    )
    out = Path(__file__).resolve().parents[2] / "data_local" / "local_lab" / "inventory_confirm.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
