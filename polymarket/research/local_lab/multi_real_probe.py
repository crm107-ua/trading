#!/usr/bin/env python3
"""
Sondeo multi-config feeds reales (paper): varias variantes × N sesiones cortas.
Genera informe JSON para teoría/funcionamiento. No on-chain.
"""

from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.batch_paper_eval import run_batch
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab"
CFG_DIR = POLY / "config"
SESSIONS = int(os.getenv("PROBE_SESSIONS", "3"))
MINUTES = float(os.getenv("PROBE_MINUTES", "2.0"))


def _variants() -> list[tuple[str, dict]]:
    risk = json.loads((CFG_DIR / "maker_demo_100_usd_risk_pack.json").read_text(encoding="utf-8"))
    hunt = json.loads((CFG_DIR / "maker_demo_100_usd_wr_hunt.json").read_text(encoding="utf-8"))
    margin = json.loads((CFG_DIR / "maker_demo_100_usd_margin_best.json").read_text(encoding="utf-8"))
    for c in (risk, hunt, margin):
        c.update(
            {
                "paper_touch_fill_every_n": 0,
                "paper_pnl_mode": "",
                "flatten_after_fill": False,
                "mean_reversion_exit": False,
                "exit_hazard_per_s": 0,
                "fair_fade_exit": True,
                "initial_capital_usdc": 100.0,
            }
        )
    # A: selectivo (WR)
    a = deepcopy(hunt)
    a["demo_label"] = "probe_selective"
    # B: balance (risk pack)
    b = deepcopy(risk)
    b["demo_label"] = "probe_balance"
    b["quote_size_shares"] = 26
    b["min_edge"] = 0.032
    b["soft_edge"] = 0.045
    b["hard_edge"] = 0.07
    b["max_entry_fills"] = 6
    # C: margen hito (referencia ingreso)
    c = deepcopy(margin)
    c["demo_label"] = "probe_margin_ref"
    c["fair_fade_exit"] = True
    c["session_kill_net_usdc"] = 10.0
    c["max_loss_usdc"] = 4.0
    c["quote_size_shares"] = 32
    c["max_entry_fills"] = 8
    return [("selective", a), ("balance", b), ("margin_ref", c)]


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "STOP_AUTONOMOUS_OOS").write_text("multi_real_probe\n", encoding="utf-8")
    report = {
        "mode": "multi_real_probe",
        "live_onchain": False,
        "ts": datetime.now(timezone.utc).isoformat(),
        "sessions_each": SESSIONS,
        "minutes_each": MINUTES,
        "variants": [],
    }
    print(json.dumps({k: report[k] for k in ("mode", "sessions_each", "minutes_each")}, indent=2), flush=True)

    for name, cfg in _variants():
        path = OUT / f"probe_{name}.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"\n######## PROBE {name} {SESSIONS}x{MINUTES}m ########", flush=True)
        summary = await run_batch(
            strategy="maker_edge",
            config=str(path),
            sessions=SESSIONS,
            minutes=MINUTES,
        )
        traded = [r for r in summary["results"] if r["fills"] > 0]
        wins = sum(1 for r in traded if r["net"] > 0)
        row = {
            "variant": name,
            "label": cfg["demo_label"],
            "size": cfg.get("quote_size_shares"),
            "min_edge": cfg.get("min_edge"),
            "max_loss": cfg.get("max_loss_usdc"),
            "win_rate": summary.get("win_rate"),
            "avg_net": summary.get("avg_net_usdc"),
            "avg_traded": summary.get("avg_net_traded_usdc"),
            "losses": summary.get("losses"),
            "traded": summary.get("sessions_with_fills"),
            "total": round(sum(r["net"] for r in summary["results"]), 2),
            "results": summary["results"],
            "wr_traded_n": f"{wins}/{len(traded)}" if traded else "0/0",
        }
        report["variants"].append(row)
        print(
            f"-> {name} WR={row['win_rate']} avg={row['avg_net']} "
            f"traded={row['traded']} total={row['total']} ({row['wr_traded_n']})",
            flush=True,
        )
        (OUT / "multi_real_probe_latest.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

    print("\n*** PROBE DONE ***", flush=True)
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
