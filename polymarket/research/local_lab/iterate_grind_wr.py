#!/usr/bin/env python3
"""Itera metodologías grind + NIM buscando WR>=75% o grind sin pérdidas.

Capitales 5/10/15€ con floors live-exact. Usa NVIDIA hybrid + grind lock.

    python -m polymarket.research.local_lab.iterate_grind_wr
    python -m polymarket.research.local_lab.iterate_grind_wr --rounds 3 --sessions 4 --minutes 4
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
from polymarket.src.ai.env_loader import load_repo_dotenv, require_nvidia_api_key
from polymarket.web_lab.catalog import apply_live_clob_floors, load_scaled_config

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "grind_iterate"

STRATS = (
    "grind_nim_selective",
    "grind_nim_best",
    "grind_nim_flow",
    "grind_nim_v1",
    "grind_nim_v2",
    "hito_margin",
    "t4_exact",
    "lock_v7",
)
CAPITALS_DEFAULT = (5.0, 10.0, 15.0)

# Mutaciones WR-push (solo si hubo fills). Starve usa STARVE_OPEN aparte.
MUTATIONS: list[dict[str, Any]] = [
    {},  # ronda 0: base del cfg
    {
        # Endurecer exits: convertir -0.18 en -0.08 y cobrar verdes antes
        "lock_profit_usdc": 0.09,
        "max_loss_usdc": 0.09,
        "stop_loss_mid": 0.007,
        "min_take_profit": 0.01,
        "max_abs_edge": 0.10,
        "min_quote_mid": 0.30,
        "max_quote_mid": 0.70,
        "flatten_before_window_s": 100,
    },
    {
        # Subir selectividad de entrada + bank micro
        "min_edge": 0.03,
        "min_z": 0.95,
        "max_abs_edge": 0.09,
        "lock_profit_usdc": 0.08,
        "max_loss_usdc": 0.08,
        "stop_loss_mid": 0.006,
        "min_quote_mid": 0.32,
        "max_quote_mid": 0.68,
    },
    {
        # WR-push final
        "min_edge": 0.032,
        "min_z": 1.0,
        "max_abs_edge": 0.085,
        "lock_profit_usdc": 0.07,
        "max_loss_usdc": 0.07,
        "pause_after_consecutive_losses": 1,
        "pause_entries_s": 900,
    },
]

# Solo si la ronda anterior se murió de hambre
STARVE_OPEN: dict[str, Any] = {
    "min_edge": 0.024,
    "min_z": 0.8,
    "min_quote_mid": 0.22,
    "max_quote_mid": 0.78,
    "quote_time_min_s": 15,
    "quote_time_max_s": 600,
    "min_expected_pnl_usdc": 0.025,
    "min_market_spread": 0.008,
    "max_abs_edge": 0.12,
    "lock_profit_usdc": 0.10,
    "max_loss_usdc": 0.10,
}


def _nim_env() -> None:
    os.environ["NVIDIA_NIM_MODE"] = "hybrid"
    os.environ["NVIDIA_NIM_PROFIT_ASSIST"] = "1"
    os.environ["NVIDIA_NIM_GRIND"] = "1"
    # Más alto → menos auto-quote rule_strong_edge (deja decidir a NIM)
    os.environ["NVIDIA_NIM_STRONG_EDGE_MULT"] = "2.8"
    os.environ["NVIDIA_NIM_EXIT_EVERY_S"] = "5"
    os.environ["NVIDIA_NIM_CONFIDENCE_MIN"] = "0.48"
    os.environ["SIM_NIM_MODEL"] = os.environ.get(
        "SIM_NIM_MODEL", "nvidia/nemotron-mini-4b-instruct"
    )
    os.environ["NVIDIA_NIM_MODEL"] = os.environ["SIM_NIM_MODEL"]
    os.environ["BATCH_STOP_AFTER_LOSS_STREAK"] = "4"
    # No abortar el batch entero por starve: necesitamos medir WR con fills
    os.environ["BATCH_STOP_AFTER_STARVE_STREAK"] = "12"


def _cfg_path(sid: str, capital: float, round_i: int, mut: dict) -> Path:
    cfg, meta = load_scaled_config(sid, capital)
    cfg["preserve_selectivity"] = True
    cfg["demo_label"] = f"grind_iter_{sid}_c{int(capital)}_r{round_i}"
    cfg = apply_live_clob_floors(cfg)
    max_sz = max(5, min(12, int(capital / 0.45)))
    sz = max(5, min(int(cfg.get("quote_size_shares") or 5), max_sz))
    cfg["quote_size_shares"] = sz
    cfg["max_quote_size_shares"] = sz
    cfg["max_inventory_shares"] = sz
    scale = capital / 10.0
    if "lock_profit_usdc" in cfg:
        cfg["lock_profit_usdc"] = round(
            max(0.06, min(0.22, float(cfg["lock_profit_usdc"]) * scale)), 2
        )
    if "max_loss_usdc" in cfg:
        cfg["max_loss_usdc"] = round(
            max(0.06, min(0.22, float(cfg["max_loss_usdc"]) * scale)), 2
        )
    for k, v in mut.items():
        cfg[k] = v
    cfg["max_entry_fills"] = 1
    cfg["no_pyramid_entries"] = True
    cfg["preserve_selectivity"] = True
    cfg["cheap_side_only"] = True
    cfg["allow_rich_side_live"] = False
    cfg["max_abs_edge"] = min(float(cfg.get("max_abs_edge") or 0.09), 0.09)
    cfg["demo_label"] = f"grind_iter_{sid}_c{int(capital)}_r{round_i}"

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"cfg_{sid}_c{int(capital)}_r{round_i}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def _metrics(summary: dict) -> dict:
    results = summary.get("results") or []
    nets = [float(r["net"]) for r in results]
    with_fills = [r for r in results if int(r.get("fills") or 0) > 0]
    wins_f = sum(1 for r in with_fills if float(r["net"]) > 0)
    losses_f = sum(1 for r in with_fills if float(r["net"]) < 0)
    flat_f = sum(1 for r in with_fills if float(r["net"]) == 0)
    wr = (wins_f / len(with_fills)) if with_fills else 0.0
    # "siempre gana poco": traded sessions never red
    no_red = losses_f == 0 and len(with_fills) > 0
    total = sum(nets) if nets else 0.0
    return {
        "wr": round(wr, 4),
        "wr_traded": round(wr, 4),
        "sessions_with_fills": len(with_fills),
        "wins_traded": wins_f,
        "losses_traded": losses_f,
        "flat_traded": flat_f,
        "no_red_traded": no_red,
        "total": round(total, 4),
        "worst": min(nets) if nets else None,
        "fills_total": sum(int(r.get("fills") or 0) for r in results),
        "hit_wr75": wr >= 0.75 and len(with_fills) >= 2,
        "hit_grind": no_red and total > 0 and len(with_fills) >= 2,
    }


async def run_cell(
    sid: str, capital: float, round_i: int, mut: dict, sessions: int, minutes: float
) -> dict:
    _nim_env()
    path = _cfg_path(sid, capital, round_i, mut)
    print(
        f"\n>>> round={round_i} {sid} EUR{capital:.0f} mut={bool(mut)} "
        f"{sessions}x{minutes}m",
        flush=True,
    )
    summary = await run_batch(
        strategy="maker_edge",
        config=str(path),
        sessions=sessions,
        minutes=minutes,
    )
    m = _metrics(summary)
    row = {
        "strategy_id": sid,
        "capital": capital,
        "round": round_i,
        "mutation": mut,
        "cfg": str(path),
        **m,
    }
    print(
        f"    WR={m['wr']} traded={m['sessions_with_fills']} total={m['total']} "
        f"no_red={m['no_red_traded']} wr75={m['hit_wr75']} grind={m['hit_grind']}",
        flush=True,
    )
    return row


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    _nim_env()
    all_rows: list[dict] = []
    champions: list[dict] = []
    rounds = max(1, int(args.rounds))
    strats = [s.strip() for s in args.strategies.split(",") if s.strip()]
    capitals = [float(x) for x in args.capitals.split(",") if x.strip()]
    last_starved = False

    for ri in range(rounds):
        if last_starved:
            mut = dict(STARVE_OPEN)
            print(
                "\n[adaptive] starve detectado -> apertura de filtros (no WR-push)",
                flush=True,
            )
        else:
            mut = dict(MUTATIONS[min(ri, len(MUTATIONS) - 1)])
        # Ronda 0: capital scout; siguientes: todos los capitals
        caps = capitals if ri > 0 or len(capitals) == 1 else [10.0]
        if args.full_capitals_each_round:
            caps = capitals
        print(f"\n========== ROUND {ri} caps={caps} mut={mut} ==========", flush=True)
        round_fills = 0
        for sid in strats:
            for capital in caps:
                try:
                    row = await run_cell(
                        sid, capital, ri, mut, args.sessions, args.minutes
                    )
                except Exception as e:
                    row = {
                        "strategy_id": sid,
                        "capital": capital,
                        "round": ri,
                        "error": f"{type(e).__name__}: {e}",
                        "wr": 0,
                        "hit_wr75": False,
                        "hit_grind": False,
                        "sessions_with_fills": 0,
                        "fills_total": 0,
                    }
                    print(f"    ERR {e}", flush=True)
                all_rows.append(row)
                round_fills += int(row.get("fills_total") or 0)
                if row.get("hit_wr75") or row.get("hit_grind"):
                    champions.append(row)
                    print("    *** CHAMPION CANDIDATE ***", flush=True)

        last_starved = round_fills == 0
        if last_starved:
            print(
                f"[adaptive] ROUND {ri} sin fills totales -> next round abre filtros",
                flush=True,
            )

        # Early stop si ya hay champion con WR>=75 y traded>=3
        strong = [
            c
            for c in champions
            if c.get("hit_wr75") and int(c.get("sessions_with_fills") or 0) >= 3
        ]
        if strong and not args.no_early_stop:
            print("\nEarly stop: WR>=75% con suficientes sesiones traded", flush=True)
            break

    # Ranking: prioriza hit_wr75, luego hit_grind, luego wr, luego total
    def rank_key(r: dict) -> tuple:
        return (
            1 if r.get("hit_wr75") else 0,
            1 if r.get("hit_grind") else 0,
            float(r.get("wr") or 0),
            float(r.get("total") or -999),
            int(r.get("sessions_with_fills") or 0),
        )

    ranked = sorted(all_rows, key=rank_key, reverse=True)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "target": "WR>=0.75 on traded sessions OR grind no-red positive total",
        "nim": {
            "mode": "hybrid",
            "profit_assist": True,
            "grind": True,
            "model": os.environ.get("NVIDIA_NIM_MODEL"),
        },
        "sessions": args.sessions,
        "minutes": args.minutes,
        "rounds_run": rounds,
        "champions": champions,
        "ranked": ranked[:20],
        "best": ranked[0] if ranked else None,
        "note": "Paper live-exact floors. No es PnL on-chain.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"iterate_{stamp}.json"
    latest = OUT / "iterate_latest.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Persist best cfg as featured-ready snapshot
    best = report.get("best")
    if best and best.get("cfg"):
        best_cfg = json.loads(Path(best["cfg"]).read_text(encoding="utf-8"))
        snap = OUT / "best_grind_cfg.json"
        snap.write_text(json.dumps(best_cfg, indent=2), encoding="utf-8")
        # Copy into frozen champ only when DNA is the 10 EUR reference.
        # Capital-scaled winners (5/15) go to a side file so we don't overwrite
        # the base maker_demo_grind_nim_best.json with size/lock from another book.
        if best.get("hit_wr75") or best.get("hit_grind"):
            capital = float(best.get("capital") or 0)
            if abs(capital - 10.0) < 1e-9:
                dest = POLY / "config" / "maker_demo_grind_nim_best.json"
                best_cfg["demo_label"] = "grind_nim_best"
                best_cfg["initial_capital_usdc"] = 10.0
                dest.write_text(json.dumps(best_cfg, indent=2), encoding="utf-8")
                print(f"Saved best cfg -> {dest}", flush=True)
            else:
                side = (
                    POLY
                    / "config"
                    / f"maker_demo_grind_nim_best_c{int(capital)}.json"
                )
                side.write_text(json.dumps(best_cfg, indent=2), encoding="utf-8")
                print(
                    f"Saved capital-scaled champ -> {side} "
                    f"(base grind_nim_best.json untouched)",
                    flush=True,
                )

    print(f"\nREPORT -> {path}", flush=True)
    print("BEST:", json.dumps(best, indent=2, ensure_ascii=False)[:1200])
    return 0 if (best and (best.get("hit_wr75") or best.get("hit_grind"))) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--minutes", type=float, default=4.0)
    ap.add_argument(
        "--strategies",
        default="grind_nim_flow,grind_nim_v1,hito_margin",
    )
    ap.add_argument("--capitals", default="5,10,15")
    ap.add_argument(
        "--full-capitals-each-round",
        action="store_true",
        help="Probar 5/10/15 en cada ronda (mas lento)",
    )
    ap.add_argument("--no-early-stop", action="store_true")
    args = ap.parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
