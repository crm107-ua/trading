#!/usr/bin/env python3
"""Caza multi-DNA en paralelo: fusion / follow / pulse / selective @5+@10.

    python -m polymarket.research.local_lab.multi_dna_hunt --parallel 6
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
OUT = POLY / "data_local" / "local_lab" / "multi_dna_hunt"

# (label, strategy_fn_id, config_file, mutations)
DNA: list[tuple[str, str, str, dict[str, Any]]] = [
    ("fusion_base", "maker_fusion", "maker_demo_fusion_router.json", {}),
    (
        "fusion_follow_heavy",
        "maker_fusion",
        "maker_demo_fusion_router.json",
        {
            "fusion_enable_edge": False,
            "follow_min_roll_usd": 0.6,
            "follow_min_vel_usd": 0.15,
            "follow_up_lo": 0.50,
            "follow_up_hi": 0.74,
            "follow_dn_lo": 0.26,
            "follow_dn_hi": 0.50,
            "min_spot_lead_usd": 1.2,
        },
    ),
    (
        "fusion_edge_mom",
        "maker_fusion",
        "maker_demo_fusion_router.json",
        {
            "fusion_enable_follow": True,
            "fusion_enable_edge": True,
            "edge_require_momentum": True,
            "edge_min_edge": 0.024,
            "min_spot_lead_usd": 1.5,
            "follow_min_roll_usd": 0.8,
        },
    ),
    ("follow_base", "maker_follow", "maker_demo_follow_gate.json", {
        "follow_min_roll_usd": 0.6,
        "follow_min_vel_usd": 0.15,
        "follow_up_lo": 0.50,
        "follow_up_hi": 0.74,
    }),
    (
        "selective_mom",
        "maker_edge",
        "maker_demo_grind_nim_best.json",
        {
            "require_momentum_align": True,
            "min_spot_lead_usd": 1.5,
            "lock_profit_usdc": 0.07,
            "max_loss_usdc": 0.07,
            "grind_bank_usdc": 0.05,
            "min_quote_mid": 0.30,
            "max_quote_mid": 0.70,
            "min_edge": 0.028,
        },
    ),
]


def _cfg(capital: float, label: str, cfg_file: str, mut: dict[str, Any]) -> Path:
    path_src = POLY / "config" / cfg_file
    cfg = json.loads(path_src.read_text(encoding="utf-8"))
    # try scaled floors if catalog knows it
    try:
        sid = cfg.get("demo_label") or "fusion_router"
        scaled, _ = load_scaled_config(sid, capital)
        cfg.update(scaled)
        cfg.update(json.loads(path_src.read_text(encoding="utf-8")))
    except Exception:
        pass
    cfg["initial_capital_usdc"] = float(capital)
    cfg["preserve_selectivity"] = True
    cfg = apply_live_clob_floors(cfg)
    cfg["quote_size_shares"] = 5
    cfg["max_quote_size_shares"] = 5
    cfg["max_inventory_shares"] = 5
    cfg["max_notional_per_side_usdc"] = 3.0
    cfg["max_inventory_usdc"] = 3.0
    for k, v in mut.items():
        cfg[k] = v
    cfg["max_entry_fills"] = 1
    cfg["demo_label"] = f"dna_{label}_c{int(capital)}"
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"cfg_{label}_c{int(capital)}.json"
    out.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return out


async def run_one(
    capital: float,
    label: str,
    strategy: str,
    cfg_file: str,
    mut: dict,
    sessions: int,
    minutes: float,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    async with sem:
        _nim_env()
        os.environ["NVIDIA_NIM_CONFIDENCE_MIN"] = "0.55"
        os.environ["BATCH_STOP_AFTER_STARVE_STREAK"] = "16"
        os.environ["BATCH_STOP_AFTER_LOSS_STREAK"] = "4"
        path = _cfg(capital, label, cfg_file, mut)
        tag = f"c{int(capital)}_{label}"
        print(f"\n>>> DNA HUNT START {tag} strat={strategy} {sessions}x{minutes}m", flush=True)
        try:
            summary = await run_batch(
                strategy=strategy,
                config=str(path),
                sessions=sessions,
                minutes=minutes,
                session_prefix=tag,
            )
            m = _metrics(summary)
            row: dict[str, Any] = {
                "label": label,
                "strategy": strategy,
                "capital": capital,
                "cfg": str(path),
                "mutation": mut,
                **m,
            }
        except Exception as e:  # noqa: BLE001
            row = {
                "label": label,
                "strategy": strategy,
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
            f"<<< DNA HUNT DONE {tag} WR={float(row.get('wr') or 0):.0%} "
            f"traded={row.get('sessions_with_fills')} total={float(row.get('total') or 0):+.2f} "
            f"{'PASS≥70%' if row['hit_wr70'] else 'FAIL'}",
            flush=True,
        )
        (OUT / f"partial_{tag}.json").write_text(
            json.dumps(row, indent=2), encoding="utf-8"
        )
        return row


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    capitals = [float(x) for x in args.capitals.split(",") if x.strip()]
    dnas = DNA
    if args.labels:
        want = {x.strip() for x in args.labels.split(",") if x.strip()}
        dnas = [d for d in DNA if d[0] in want]
        if not dnas:
            raise SystemExit(f"no labels matched {want}")

    jobs = [(c, *d) for c in capitals for d in dnas]
    sem = asyncio.Semaphore(max(1, int(args.parallel)))
    print(
        f"\n===== MULTI-DNA workers={args.parallel} jobs={len(jobs)} "
        f"caps={capitals} labels={[d[0] for d in dnas]} "
        f"{args.sessions}x{args.minutes}m =====",
        flush=True,
    )
    rows_l = list(
        await asyncio.gather(
            *[
                run_one(c, lab, strat, cfgf, mut, args.sessions, args.minutes, sem)
                for c, lab, strat, cfgf, mut in jobs
            ]
        )
    )

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
        "method": "multi_dna",
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
        # Keep strategy hint in notes; paper runner uses strategy arg at promo time
        champ["demo_label"] = "grind_nim_best"
        champ["notes"] = (
            f"MULTI-DNA {stamp}: "
            + ", ".join(
                f"{int(c)}€ WR{winners[c]['wr']:.0%} ({winners[c]['label']}/{winners[c]['strategy']})"
                for c in sorted(winners)
            )
            + ". Paper feeds reales. No on-chain."
        )
        champ["_promo_strategy"] = best10["strategy"]
        dest = POLY / "config" / "maker_demo_grind_nim_best.json"
        # Only overwrite champ cfg if strategy is maker_edge-compatible fields;
        # always write fusion/follow winners to their own promo file too.
        promo = POLY / "config" / f"maker_demo_promo_{best10['label']}.json"
        promo.write_text(json.dumps(champ, indent=2) + "\n", encoding="utf-8")
        if best10["strategy"] == "maker_edge":
            dest.write_text(json.dumps(champ, indent=2) + "\n", encoding="utf-8")
            print(f"\nPROMOTED EDGE -> {dest}", flush=True)
        print(f"PROMO SNAPSHOT -> {promo}", flush=True)

    print(f"\nREPORT -> {path}", flush=True)
    for c in capitals:
        w = winners.get(c)
        if w:
            print(
                f"  ✓ {c:.0f}€ WR={w['wr']:.0%} {w['label']}/{w['strategy']} total={w['total']:+.2f}",
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
                    f"{best_c.get('label')} traded={best_c.get('sessions_with_fills')} "
                    f"total={float(best_c.get('total') or 0):+.2f}",
                    flush=True,
                )
    print("BOTH_READY:", report["both_ready"], flush=True)
    return 0 if report["both_ready"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capitals", default="5,10")
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--minutes", type=float, default=4.0)
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--labels", default="")
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
