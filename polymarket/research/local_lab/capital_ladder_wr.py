#!/usr/bin/env python3
"""Escalera de capital 5→100€ + escenarios WR para grind selective.

WR-first: size micro fijo, lock/loss acotados. Feeds reales (paper live-exact).

    python -m polymarket.research.local_lab.capital_ladder_wr
    python -m polymarket.research.local_lab.capital_ladder_wr --phase scout
    python -m polymarket.research.local_lab.capital_ladder_wr --phase confirm --capitals 10,25,50,100
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
OUT = POLY / "data_local" / "local_lab" / "capital_ladder"

CAPITALS_DEFAULT = (5.0, 10.0, 15.0, 25.0, 50.0, 100.0)

# Escenarios: DNA selectivo + variantes de perfeccionamiento WR
SCENARIOS: dict[str, dict[str, Any]] = {
    "base": {
        # DNA campeón selective v2
    },
    "edge_tight": {
        "min_edge": 0.033,
        "min_z": 1.05,
        "soft_edge": 0.044,
        "max_abs_edge": 0.08,
        "min_expected_pnl_usdc": 0.06,
    },
    "lock_hard": {
        "lock_profit_usdc": 0.08,
        "max_loss_usdc": 0.08,
        "stop_loss_mid": 0.006,
        "flatten_before_window_s": 100,
        "min_take_profit": 0.01,
    },
    "mid_center": {
        "min_quote_mid": 0.34,
        "max_quote_mid": 0.66,
        "min_edge": 0.032,
        "min_z": 1.0,
    },
    "combo_wr": {
        # Selectividad + corte duro (mejor candidato multi-capital)
        "min_edge": 0.032,
        "min_z": 1.05,
        "soft_edge": 0.043,
        "max_abs_edge": 0.08,
        "lock_profit_usdc": 0.08,
        "max_loss_usdc": 0.08,
        "stop_loss_mid": 0.006,
        "flatten_before_window_s": 100,
        "min_expected_pnl_usdc": 0.055,
        "pause_after_consecutive_losses": 1,
        "pause_entries_s": 900,
    },
}


def _build_cfg(
    sid: str, capital: float, scenario: str, mut: dict[str, Any]
) -> Path:
    """Config WR-first: size micro, lock/loss no explotan con capital alto."""
    cfg, _meta = load_scaled_config(sid, capital)
    cfg["preserve_selectivity"] = True
    cfg["initial_capital_usdc"] = float(capital)
    cfg["currency_label"] = "EUR"
    cfg = apply_live_clob_floors(cfg)

    # Micro size fijo (WR): más capital = más buffer, NO más riesgo por trade
    sz = 5
    cfg["quote_size_shares"] = sz
    cfg["max_quote_size_shares"] = sz
    cfg["max_inventory_shares"] = sz
    # Notional acotado al micro (5 sh * ~0.55 ≈ 2.75)
    notion = min(3.0, max(2.75, float(capital) * 0.08))
    cfg["max_notional_per_side_usdc"] = round(min(notion, float(capital) * 0.5), 2)
    cfg["max_inventory_usdc"] = cfg["max_notional_per_side_usdc"]

    # Lock/loss: banda grind estrecha (no escalar × capital)
    lock = float(cfg.get("lock_profit_usdc") or 0.10)
    loss = float(cfg.get("max_loss_usdc") or 0.10)
    cfg["lock_profit_usdc"] = round(max(0.07, min(0.12, lock)), 2)
    cfg["max_loss_usdc"] = round(max(0.07, min(0.12, loss)), 2)
    # Kill de sesión escala suave con capital (buffer)
    cfg["session_kill_net_usdc"] = round(
        max(0.35, min(1.5, 0.35 * (1.0 + capital / 50.0))), 2
    )

    sc = SCENARIOS.get(scenario) or {}
    for k, v in sc.items():
        cfg[k] = v
    for k, v in mut.items():
        cfg[k] = v

    cfg["max_entry_fills"] = 1
    cfg["no_pyramid_entries"] = True
    cfg["cheap_side_only"] = True
    cfg["allow_rich_side_live"] = False
    cfg["max_abs_edge"] = min(float(cfg.get("max_abs_edge") or 0.085), 0.09)
    cfg["demo_label"] = f"ladder_{sid}_{scenario}_c{int(capital)}"

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"cfg_{sid}_{scenario}_c{int(capital)}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


async def run_cell(
    sid: str,
    capital: float,
    scenario: str,
    sessions: int,
    minutes: float,
    mut: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _nim_env()
    os.environ["NVIDIA_NIM_CONFIDENCE_MIN"] = os.environ.get(
        "NVIDIA_NIM_CONFIDENCE_MIN", "0.55"
    )
    mut = mut or {}
    path = _build_cfg(sid, capital, scenario, mut)
    print(
        f"\n>>> {sid} scen={scenario} EUR{capital:.0f} {sessions}x{minutes}m",
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
        "scenario": scenario,
        "capital": capital,
        "cfg": str(path),
        "mutation": mut,
        **m,
    }
    print(
        f"    WR={m['wr']} traded={m['sessions_with_fills']} total={m['total']} "
        f"worst={m['worst']} wr75={m['hit_wr75']} grind={m['hit_grind']}",
        flush=True,
    )
    return row


def _rank_key(r: dict[str, Any]) -> tuple:
    return (
        1 if r.get("hit_wr75") else 0,
        1 if r.get("hit_grind") else 0,
        float(r.get("wr") or 0),
        float(r.get("total") or -999),
        int(r.get("sessions_with_fills") or 0),
    )


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    _nim_env()
    capitals = [float(x) for x in args.capitals.split(",") if x.strip()]
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    for s in scenarios:
        if s not in SCENARIOS:
            raise SystemExit(f"unknown scenario {s!r}; choose from {list(SCENARIOS)}")

    if args.phase == "scout":
        sessions, minutes = args.scout_sessions, args.scout_minutes
    elif args.phase == "confirm":
        sessions, minutes = args.confirm_sessions, args.confirm_minutes
    else:
        sessions, minutes = args.scout_sessions, args.scout_minutes

    rows: list[dict[str, Any]] = []
    print(
        f"\n===== LADDER phase={args.phase} sid={args.strategy} "
        f"caps={capitals} scens={scenarios} {sessions}x{minutes}m =====",
        flush=True,
    )

    for scenario in scenarios:
        for capital in capitals:
            try:
                row = await run_cell(
                    args.strategy, capital, scenario, sessions, minutes
                )
            except Exception as e:  # noqa: BLE001
                row = {
                    "strategy_id": args.strategy,
                    "scenario": scenario,
                    "capital": capital,
                    "error": f"{type(e).__name__}: {e}",
                    "wr": 0,
                    "hit_wr75": False,
                    "hit_grind": False,
                    "sessions_with_fills": 0,
                    "fills_total": 0,
                    "total": 0,
                }
                print(f"    ERR {e}", flush=True)
            rows.append(row)

    # Autotune: reintentar celdas fallidas con combo_wr si no era ya combo
    if args.autotune and args.phase in {"scout", "all"}:
        weak = [
            r
            for r in rows
            if not r.get("error")
            and not r.get("hit_wr75")
            and int(r.get("sessions_with_fills") or 0) >= 1
            and r.get("scenario") != "combo_wr"
        ]
        if weak:
            print(
                f"\n===== AUTOTUNE combo_wr on {len(weak)} weak cells =====",
                flush=True,
            )
            for w in weak:
                try:
                    row = await run_cell(
                        args.strategy,
                        float(w["capital"]),
                        "combo_wr",
                        sessions,
                        minutes,
                    )
                    row["autotune_from"] = w.get("scenario")
                    rows.append(row)
                except Exception as e:  # noqa: BLE001
                    print(f"    AUTOTUNE ERR {e}", flush=True)

    ranked = sorted(rows, key=_rank_key, reverse=True)
    by_capital: dict[str, list] = {}
    for r in rows:
        by_capital.setdefault(str(r.get("capital")), []).append(r)

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "phase": args.phase,
        "strategy": args.strategy,
        "target": "WR>=0.75 on traded sessions, prefer grind no-red",
        "note": "Paper feeds reales. Size micro fijo. No es PnL on-chain.",
        "sessions": sessions,
        "minutes": minutes,
        "capitals": capitals,
        "scenarios": scenarios,
        "rows": rows,
        "ranked": ranked[:30],
        "best": ranked[0] if ranked else None,
        "wr75_cells": [r for r in rows if r.get("hit_wr75")],
        "summary_by_capital": {
            k: sorted(v, key=_rank_key, reverse=True)[0]
            for k, v in by_capital.items()
            if v
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"ladder_{args.phase}_{stamp}.json"
    latest = OUT / "ladder_latest.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Persist best combo cfg snapshot
    best = report.get("best")
    if best and best.get("cfg") and (best.get("hit_wr75") or best.get("hit_grind")):
        snap = OUT / "best_ladder_cfg.json"
        snap.write_text(Path(best["cfg"]).read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Saved ladder best cfg -> {snap}", flush=True)

    print(f"\nREPORT -> {path}", flush=True)
    print("BEST:", json.dumps(best, indent=2, ensure_ascii=False)[:1400])
    n_ok = len(report["wr75_cells"])
    n_tot = len([r for r in rows if not r.get("error")])
    print(f"WR75 cells: {n_ok}/{n_tot}", flush=True)
    return 0 if n_ok > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Capital ladder WR 5→100€")
    ap.add_argument("--phase", choices=("scout", "confirm", "all"), default="scout")
    ap.add_argument("--strategy", default="grind_nim_selective")
    ap.add_argument("--capitals", default="5,10,15,25,50,100")
    ap.add_argument(
        "--scenarios",
        default="base,combo_wr",
        help=f"comma list from {list(SCENARIOS)}",
    )
    ap.add_argument("--scout-sessions", type=int, default=4)
    ap.add_argument("--scout-minutes", type=float, default=3.5)
    ap.add_argument("--confirm-sessions", type=int, default=6)
    ap.add_argument("--confirm-minutes", type=float, default=5.0)
    ap.add_argument(
        "--autotune",
        action="store_true",
        help="Reintentar celdas débiles con combo_wr",
    )
    args = ap.parse_args()
    if args.phase == "all":
        # scout then confirm top capitals from env override — run scout only here;
        # caller can chain confirm.
        args.phase = "scout"
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
