#!/usr/bin/env python3
"""Caza rápida WR>=70% @5€ y @10€ con DNA wr_lock + mutaciones.

    python -m polymarket.research.local_lab.wr_lock_hunt
    python -m polymarket.research.local_lab.wr_lock_hunt --capitals 5,10 --sessions 4 --minutes 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.batch_paper_eval import run_batch
from polymarket.research.local_lab.iterate_grind_wr import _metrics, _nim_env
from polymarket.src.ai.env_loader import load_repo_dotenv, require_nvidia_api_key
from polymarket.web_lab.catalog import apply_live_clob_floors, load_scaled_config

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "wr_lock_hunt"
SID = "grind_nim_wr_lock"

# Mutaciones ordenadas: de fusión base a más selectivas
VARIANTS: list[tuple[str, dict[str, Any]]] = [
    ("wr_lock", {}),
    (
        "edge_open_mid",
        {
            # Más edge, mid del campeón (evita starve de mid estrecho)
            "min_edge": 0.034,
            "min_z": 1.1,
            "min_quote_mid": 0.28,
            "max_quote_mid": 0.72,
            "max_abs_edge": 0.08,
        },
    ),
    (
        "scalpel",
        {
            "min_edge": 0.033,
            "min_z": 1.08,
            "lock_profit_usdc": 0.07,
            "max_loss_usdc": 0.07,
            "grind_bank_usdc": 0.05,
            "stop_loss_mid": 0.005,
            "min_quote_mid": 0.30,
            "max_quote_mid": 0.70,
        },
    ),
    (
        "selective_v2_plus",
        {
            # DNA que dio WR100% @10 + cortes más duros
            "min_edge": 0.031,
            "min_z": 1.0,
            "min_quote_mid": 0.28,
            "max_quote_mid": 0.72,
            "max_abs_edge": 0.085,
            "lock_profit_usdc": 0.08,
            "max_loss_usdc": 0.08,
            "grind_bank_usdc": 0.055,
        },
    ),
]


def _cfg(capital: float, variant: str, mut: dict[str, Any]) -> Path:
    # Prefer wr_lock file; fall back to selective catalog id if missing from catalog
    try:
        cfg, _ = load_scaled_config(SID, capital)
    except Exception:
        cfg, _ = load_scaled_config("grind_nim_selective", capital)
    cfg.update(json.loads((POLY / "config" / "maker_demo_grind_nim_wr_lock.json").read_text()))
    cfg["initial_capital_usdc"] = float(capital)
    cfg["preserve_selectivity"] = True
    cfg = apply_live_clob_floors(cfg)
    cfg["quote_size_shares"] = 5
    cfg["max_quote_size_shares"] = 5
    cfg["max_inventory_shares"] = 5
    cfg["max_notional_per_side_usdc"] = 3.0
    cfg["max_inventory_usdc"] = 3.0
    cfg["lock_profit_usdc"] = round(
        max(0.07, min(0.12, float(cfg.get("lock_profit_usdc") or 0.08))), 2
    )
    cfg["max_loss_usdc"] = round(
        max(0.07, min(0.12, float(cfg.get("max_loss_usdc") or 0.08))), 2
    )
    for k, v in mut.items():
        cfg[k] = v
    cfg["cheap_side_only"] = True
    cfg["allow_rich_side_live"] = False
    cfg["max_entry_fills"] = 1
    cfg["demo_label"] = f"wr_lock_{variant}_c{int(capital)}"
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"cfg_{variant}_c{int(capital)}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


async def run_one(
    capital: float, variant: str, mut: dict, sessions: int, minutes: float
) -> dict[str, Any]:
    _nim_env()
    os.environ["NVIDIA_NIM_CONFIDENCE_MIN"] = "0.58"
    os.environ["NVIDIA_NIM_STRONG_EDGE_MULT"] = "3.0"
    path = _cfg(capital, variant, mut)
    print(f"\n>>> HUNT {variant} EUR{capital:.0f} {sessions}x{minutes}m", flush=True)
    summary = await run_batch(
        strategy="maker_edge", config=str(path), sessions=sessions, minutes=minutes
    )
    m = _metrics(summary)
    row = {
        "variant": variant,
        "capital": capital,
        "cfg": str(path),
        "mutation": mut,
        **m,
    }
    # Umbral prep-inversión: WR>=70% con al menos 2 sesiones traded
    row["hit_wr70"] = bool(
        float(m["wr"]) >= 0.70 and int(m["sessions_with_fills"]) >= 2
    )
    print(
        f"    → WR={m['wr']:.0%} traded={m['sessions_with_fills']} "
        f"total={m['total']:+.2f} worst={m['worst']} "
        f"{'PASS≥70%' if row['hit_wr70'] else 'FAIL'}",
        flush=True,
    )
    return row


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    capitals = [float(x) for x in args.capitals.split(",") if x.strip()]
    rows: list[dict] = []
    winners: dict[float, dict] = {}

    for capital in capitals:
        print(f"\n######## CAPITAL {capital:.0f} EUR — objetivo WR≥70% ########", flush=True)
        for variant, mut in VARIANTS:
            row = await run_one(capital, variant, mut, args.sessions, args.minutes)
            rows.append(row)
            if row.get("hit_wr70"):
                prev = winners.get(capital)
                if prev is None or float(row["wr"]) > float(prev["wr"]) or (
                    float(row["wr"]) == float(prev["wr"])
                    and float(row["total"]) > float(prev["total"])
                ):
                    winners[capital] = row
                if not args.exhaust:
                    print(f"    ✓ {capital:.0f}€ asegurado con {variant}", flush=True)
                    break
        if capital not in winners:
            print(f"    ✗ {capital:.0f}€ sin WR≥70% en este pase", flush=True)

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "target": "WR>=0.70 @5 and @10 with traded>=2",
        "sessions": args.sessions,
        "minutes": args.minutes,
        "rows": rows,
        "winners": {str(k): v for k, v in winners.items()},
        "both_ready": all(c in winners for c in capitals),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"hunt_{stamp}.json"
    latest = OUT / "hunt_latest.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if report["both_ready"]:
        # Promover mejor DNA @10 (o @5 si solo hay uno) a wr_lock + best
        best10 = winners.get(10.0) or next(iter(winners.values()))
        champ = json.loads(Path(best10["cfg"]).read_text(encoding="utf-8"))
        champ["demo_label"] = "grind_nim_best"
        champ["notes"] = (
            f"WR-LOCK promovido {stamp}: "
            + ", ".join(
                f"{int(c)}€ WR{winners[c]['wr']:.0%} ({winners[c]['variant']})"
                for c in sorted(winners)
            )
            + ". Prep inversión — paper feeds reales. No on-chain."
        )
        dest = POLY / "config" / "maker_demo_grind_nim_best.json"
        dest.write_text(json.dumps(champ, indent=2) + "\n", encoding="utf-8")
        (POLY / "config" / "maker_demo_grind_nim_wr_lock.json").write_text(
            json.dumps({**champ, "demo_label": "grind_nim_wr_lock"}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nPROMOTED -> {dest}", flush=True)

    print(f"\nREPORT -> {path}", flush=True)
    print("WINNERS:", json.dumps(report["winners"], indent=2, ensure_ascii=False)[:2000])
    print("BOTH_READY:", report["both_ready"], flush=True)
    return 0 if report["both_ready"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capitals", default="5,10")
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument(
        "--exhaust",
        action="store_true",
        help="Probar todas las variantes aunque ya haya PASS",
    )
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
