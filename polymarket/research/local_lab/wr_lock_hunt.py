#!/usr/bin/env python3
"""Caza WR>=70% @5€/@10€ — paralelizable por capital y variante.

    python -m polymarket.research.local_lab.wr_lock_hunt --parallel 4
    python -m polymarket.research.local_lab.wr_lock_hunt --capitals 5 --parallel 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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

VARIANTS: list[tuple[str, dict[str, Any]]] = [
    ("wr_lock", {}),
    (
        "edge_open_mid",
        {
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
    try:
        cfg, _ = load_scaled_config(SID, capital)
    except Exception:
        cfg, _ = load_scaled_config("grind_nim_selective", capital)
    cfg.update(
        json.loads((POLY / "config" / "maker_demo_grind_nim_wr_lock.json").read_text())
    )
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
    capital: float,
    variant: str,
    mut: dict,
    sessions: int,
    minutes: float,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    async with sem:
        _nim_env()
        os.environ["NVIDIA_NIM_CONFIDENCE_MIN"] = "0.58"
        os.environ["NVIDIA_NIM_STRONG_EDGE_MULT"] = "3.0"
        # Starve menos agresivo en caza paralela (queremos medir WR)
        os.environ["BATCH_STOP_AFTER_STARVE_STREAK"] = "12"
        os.environ["BATCH_STOP_AFTER_LOSS_STREAK"] = "4"
        path = _cfg(capital, variant, mut)
        tag = f"c{int(capital)}_{variant}"
        print(f"\n>>> HUNT START {tag} {sessions}x{minutes}m", flush=True)
        try:
            summary = await run_batch(
                strategy="maker_edge",
                config=str(path),
                sessions=sessions,
                minutes=minutes,
                session_prefix=tag,
            )
            m = _metrics(summary)
            row: dict[str, Any] = {
                "variant": variant,
                "capital": capital,
                "cfg": str(path),
                "mutation": mut,
                **m,
            }
        except Exception as e:  # noqa: BLE001
            row = {
                "variant": variant,
                "capital": capital,
                "cfg": str(path),
                "mutation": mut,
                "error": f"{type(e).__name__}: {e}",
                "wr": 0.0,
                "sessions_with_fills": 0,
                "total": 0.0,
                "worst": None,
            }
        row["hit_wr70"] = bool(
            float(row.get("wr") or 0) >= 0.70
            and int(row.get("sessions_with_fills") or 0) >= 2
        )
        print(
            f"<<< HUNT DONE {tag} WR={float(row.get('wr') or 0):.0%} "
            f"traded={row.get('sessions_with_fills')} total={float(row.get('total') or 0):+.2f} "
            f"{'PASS≥70%' if row['hit_wr70'] else 'FAIL'}",
            flush=True,
        )
        # Persist partial result immediately (subagent-friendly)
        partial = OUT / f"partial_{tag}.json"
        partial.write_text(json.dumps(row, indent=2), encoding="utf-8")
        return row


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    capitals = [float(x) for x in args.capitals.split(",") if x.strip()]
    variants = VARIANTS
    if args.variants:
        want = {v.strip() for v in args.variants.split(",") if v.strip()}
        variants = [(n, m) for n, m in VARIANTS if n in want]
        if not variants:
            raise SystemExit(f"no variants matched {want}")

    jobs = [(c, n, m) for c in capitals for n, m in variants]
    # Early-stop mode: still launch all in parallel; pick winners after
    sem = asyncio.Semaphore(max(1, int(args.parallel)))
    print(
        f"\n===== PARALLEL HUNT workers={args.parallel} jobs={len(jobs)} "
        f"caps={capitals} variants={[n for n,_ in variants]} "
        f"{args.sessions}x{args.minutes}m =====",
        flush=True,
    )
    rows = await asyncio.gather(
        *[
            run_one(c, n, m, args.sessions, args.minutes, sem)
            for c, n, m in jobs
        ]
    )
    rows_l = list(rows)

    winners: dict[float, dict] = {}
    for row in rows_l:
        if not row.get("hit_wr70"):
            continue
        c = float(row["capital"])
        prev = winners.get(c)
        if prev is None or float(row["wr"]) > float(prev["wr"]) or (
            float(row["wr"]) == float(prev["wr"])
            and float(row.get("total") or 0) > float(prev.get("total") or 0)
        ):
            winners[c] = row

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "target": "WR>=0.70 @5 and @10 with traded>=2",
        "parallel": args.parallel,
        "sessions": args.sessions,
        "minutes": args.minutes,
        "rows": rows_l,
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
        best10 = winners.get(10.0) or next(iter(winners.values()))
        champ = json.loads(Path(best10["cfg"]).read_text(encoding="utf-8"))
        champ["demo_label"] = "grind_nim_best"
        champ["notes"] = (
            f"WR-LOCK paralelo {stamp}: "
            + ", ".join(
                f"{int(c)}€ WR{winners[c]['wr']:.0%} ({winners[c]['variant']})"
                for c in sorted(winners)
            )
            + ". Prep inversión — paper feeds reales. No on-chain."
        )
        dest = POLY / "config" / "maker_demo_grind_nim_best.json"
        dest.write_text(json.dumps(champ, indent=2) + "\n", encoding="utf-8")
        (POLY / "config" / "maker_demo_grind_nim_wr_lock.json").write_text(
            json.dumps({**champ, "demo_label": "grind_nim_wr_lock"}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(f"\nPROMOTED -> {dest}", flush=True)

    print(f"\nREPORT -> {path}", flush=True)
    for c in capitals:
        w = winners.get(c)
        if w:
            print(
                f"  ✓ {c:.0f}€ WR={w['wr']:.0%} variant={w['variant']} total={w['total']:+.2f}",
                flush=True,
            )
        else:
            best_c = max(
                (r for r in rows_l if float(r["capital"]) == c),
                key=lambda r: (float(r.get("wr") or 0), float(r.get("total") or 0)),
                default=None,
            )
            if best_c:
                print(
                    f"  ✗ {c:.0f}€ best WR={float(best_c.get('wr') or 0):.0%} "
                    f"variant={best_c.get('variant')} total={float(best_c.get('total') or 0):+.2f}",
                    flush=True,
                )
    print("BOTH_READY:", report["both_ready"], flush=True)
    return 0 if report["both_ready"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capitals", default="5,10")
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument(
        "--parallel",
        type=int,
        default=4,
        help="celdas concurrentes (capital×variante)",
    )
    ap.add_argument(
        "--variants",
        default="",
        help="subset comma: wr_lock,edge_open_mid,scalpel,selective_v2_plus",
    )
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
