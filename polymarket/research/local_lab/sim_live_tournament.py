#!/usr/bin/env python3
"""Torneo simulación live-exact: capitales 5/10/15€ × metodologías × reglas vs NIM.

Replica floors CLOB (min 5 shares, notional, kills) en paper — NO envía órdenes.
Puntúa cada combinación y itera hasta elegir ganadora.

    python -m polymarket.research.local_lab.sim_live_tournament
    python -m polymarket.research.local_lab.sim_live_tournament --phase scout
    python -m polymarket.research.local_lab.sim_live_tournament --phase finals
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.batch_paper_eval import run_batch
from polymarket.src.ai.env_loader import load_repo_dotenv, require_nvidia_api_key
from polymarket.src.ai.nvidia_client import cache_models, pick_fast_models, primary_model_id
from polymarket.web_lab.catalog import FEATURED, apply_live_clob_floors, load_scaled_config

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "sim_live_tournament"

# Metodologías del plan + strict
STRATEGY_IDS = [
    "t4_exact",
    "t4_risk_up",
    "fuse_v3",
    "micro_5",
    "micro_strict",
    "lock_v7",
    "hito_margin",
    "grind_nim_v1",
    "grind_nim_v2",
]

CAPITALS = (5.0, 10.0, 15.0)

# A/B decision stack
MODES = {
    "rules": {
        "NVIDIA_NIM_MODE": "fast",
        "NVIDIA_NIM_PROFIT_ASSIST": "0",
    },
    "nim_hybrid": {
        "NVIDIA_NIM_MODE": "hybrid",
        "NVIDIA_NIM_PROFIT_ASSIST": "1",
        "NVIDIA_NIM_STRONG_EDGE_MULT": "1.55",
        "NVIDIA_NIM_EXIT_EVERY_S": "6",
        "NVIDIA_NIM_CONFIDENCE_MIN": "0.50",
        # Preferir nemotron mini en torneo (override: SIM_NIM_MODEL)
        "NVIDIA_NIM_MODEL": os.environ.get(
            "SIM_NIM_MODEL", "nvidia/nemotron-mini-4b-instruct"
        ),
    },
}


def _apply_env(mode: str) -> None:
    for k, v in MODES[mode].items():
        os.environ[k] = v
    # Torneo: no matar demasiado pronto (queremos señal)
    os.environ["BATCH_STOP_AFTER_LOSS_STREAK"] = os.getenv(
        "SIM_LOSS_STREAK", "3"
    )
    os.environ["BATCH_STOP_AFTER_STARVE_STREAK"] = os.getenv(
        "SIM_STARVE_STREAK", "3"
    )


def _live_exact_cfg(strategy_id: str, capital: float) -> tuple[dict, dict, Path]:
    cfg, meta = load_scaled_config(strategy_id, capital)
    cfg = apply_live_clob_floors(cfg)
    # Cap size al capital (evita micro_strict base 1.2€ → size 42 a 10€)
    max_sz = max(5, min(20, int(capital / 0.4)))
    sz = max(5, min(int(cfg.get("quote_size_shares") or 5), max_sz))
    cfg["quote_size_shares"] = sz
    cfg["max_quote_size_shares"] = max(sz, min(int(cfg.get("max_quote_size_shares") or sz), max_sz))
    cfg["max_inventory_shares"] = cfg["max_quote_size_shares"]
    # Paper con disciplina live
    cfg["sim_live_exact"] = True
    cfg["demo_label"] = f"sim_live_{strategy_id}_{int(capital)}"
    cfg["max_entry_fills"] = max(1, min(int(cfg.get("max_entry_fills") or 2), 3))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"cfg_{strategy_id}_c{int(capital)}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg, meta, path


def score_row(row: dict[str, Any]) -> float:
    """Score compuesto: PnL + WR + cola + actividad (penaliza starve)."""
    total = float(row.get("total") if row.get("total") is not None else -999)
    wr = float(row.get("wr") or 0.0)
    worst = float(row.get("worst") if row.get("worst") is not None else -5.0)
    traded = int(row.get("sessions_with_fills") or 0)
    fills = int(row.get("fills_total") or 0)
    starve = 1.0 if traded <= 0 else 0.0
    # Normalizar un poco por capital
    cap = max(1.0, float(row.get("capital") or 10.0))
    pnl_norm = total / (cap / 10.0)
    return round(
        pnl_norm * 2.5
        + wr * 10.0
        + worst * 0.8
        + min(traded, 4) * 0.6
        + min(fills, 12) * 0.05
        - starve * 6.0,
        4,
    )


async def _run_one(
    *,
    strategy_id: str,
    capital: float,
    mode: str,
    sessions: int,
    minutes: float,
) -> dict[str, Any]:
    _apply_env(mode)
    cfg, meta, cfg_path = _live_exact_cfg(strategy_id, capital)
    print(
        f"\n>>> {strategy_id} | €{capital:.0f} | {mode} | "
        f"{sessions}x{minutes}m | size={cfg.get('quote_size_shares')}",
        flush=True,
    )
    try:
        summary = await run_batch(
            strategy="maker_edge",
            config=str(cfg_path),
            sessions=sessions,
            minutes=minutes,
        )
    except Exception as e:
        return {
            "strategy_id": strategy_id,
            "name": meta.get("name"),
            "capital": capital,
            "mode": mode,
            "error": f"{type(e).__name__}: {e}",
            "total": None,
            "wr": None,
            "worst": None,
            "sessions_with_fills": 0,
            "fills_total": 0,
            "score": -99.0,
        }

    results = summary.get("results") or []
    nets = [float(r["net"]) for r in results]
    fills_total = sum(int(r.get("fills") or 0) for r in results)
    row = {
        "strategy_id": strategy_id,
        "name": meta.get("name"),
        "badge": next(
            (f.get("badge") for f in FEATURED if f["id"] == strategy_id), None
        ),
        "capital": capital,
        "mode": mode,
        "nim_mode": os.environ.get("NVIDIA_NIM_MODE"),
        "profit_assist": os.environ.get("NVIDIA_NIM_PROFIT_ASSIST"),
        "model": primary_model_id(),
        "sessions": len(results),
        "minutes": minutes,
        "total": round(sum(nets), 4) if nets else 0.0,
        "wr": summary.get("win_rate"),
        "worst": min(nets) if nets else None,
        "avg_net": summary.get("avg_net_usdc"),
        "avg_net_traded": summary.get("avg_net_traded_usdc"),
        "sessions_with_fills": summary.get("sessions_with_fills"),
        "fills_total": fills_total,
        "wins": summary.get("wins"),
        "losses": summary.get("losses"),
        "stopped_early_starve": summary.get("stopped_early_starve"),
        "cfg": str(cfg_path),
        "live_floors": {
            "size": cfg.get("quote_size_shares"),
            "max_notional": cfg.get("max_notional_usdc")
            or cfg.get("max_notional_per_side_usdc"),
            "min_edge": cfg.get("min_edge"),
            "mid": f"{cfg.get('min_quote_mid')}-{cfg.get('max_quote_mid')}",
        },
    }
    row["score"] = score_row(row)
    print(
        f"    total={row['total']} wr={row['wr']} worst={row['worst']} "
        f"fills={fills_total} score={row['score']}",
        flush=True,
    )
    return row


async def phase_scout(
    *,
    sessions: int,
    minutes: float,
    capitals: list[float] | None = None,
) -> list[dict]:
    """Ronda 1: capital medio (10) o lista, todas las strats × 2 modos."""
    caps = capitals or [10.0]
    rows: list[dict] = []
    for capital in caps:
        for sid in STRATEGY_IDS:
            if not any(f["id"] == sid for f in FEATURED):
                continue
            for mode in ("rules", "nim_hybrid"):
                rows.append(
                    await _run_one(
                        strategy_id=sid,
                        capital=capital,
                        mode=mode,
                        sessions=sessions,
                        minutes=minutes,
                    )
                )
    return rows


async def phase_finals(
    contenders: list[dict],
    *,
    sessions: int,
    minutes: float,
) -> list[dict]:
    """Ronda 2: top combos en 5/10/15€ (modo ganador de cada strat)."""
    # Mejor fila por strategy_id
    best_by: dict[str, dict] = {}
    for r in contenders:
        if r.get("error"):
            continue
        sid = r["strategy_id"]
        prev = best_by.get(sid)
        if prev is None or float(r.get("score") or -99) > float(prev.get("score") or -99):
            best_by[sid] = r
    # Top 3 strategies (equilibrio cobertura vs tiempo de lab)
    tops = sorted(best_by.values(), key=lambda x: float(x.get("score") or -99), reverse=True)[
        :3
    ]
    rows: list[dict] = []
    for base in tops:
        for capital in CAPITALS:
            rows.append(
                await _run_one(
                    strategy_id=base["strategy_id"],
                    capital=capital,
                    mode=str(base.get("mode") or "nim_hybrid"),
                    sessions=sessions,
                    minutes=minutes,
                )
            )
    return rows


def _write_report(phase: str, rows: list[dict], extra: dict | None = None) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ranked = sorted(rows, key=lambda x: float(x.get("score") or -99), reverse=True)
    # Mejor overall y mejor con NIM
    best = ranked[0] if ranked else None
    best_nim = next((r for r in ranked if r.get("mode") == "nim_hybrid"), None)
    best_rules = next((r for r in ranked if r.get("mode") == "rules"), None)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "note": (
            "Simulación paper con floors live-exact (min 5 sh). "
            "NO es PnL on-chain. Compara rules vs NVIDIA NIM hybrid+assist."
        ),
        "model": primary_model_id(),
        "ranked": ranked,
        "winner": best,
        "best_nim": best_nim,
        "best_rules": best_rules,
        "nim_vs_rules": _compare_nim_lift(rows),
        **(extra or {}),
    }
    path = OUT / f"{phase}_{stamp}.json"
    latest = OUT / f"{phase}_latest.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "leaderboard_latest.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return path


def _compare_nim_lift(rows: list[dict]) -> list[dict]:
    """Por (strategy, capital): score nim - score rules."""
    by_key: dict[tuple, dict] = {}
    for r in rows:
        if r.get("error"):
            continue
        key = (r["strategy_id"], float(r["capital"]))
        by_key.setdefault(key, {})[r["mode"]] = r
    out = []
    for (sid, cap), modes in sorted(by_key.items()):
        a, b = modes.get("rules"), modes.get("nim_hybrid")
        if not a or not b:
            continue
        out.append(
            {
                "strategy_id": sid,
                "capital": cap,
                "score_rules": a.get("score"),
                "score_nim": b.get("score"),
                "lift": round(float(b.get("score") or 0) - float(a.get("score") or 0), 4),
                "total_rules": a.get("total"),
                "total_nim": b.get("total"),
                "wr_rules": a.get("wr"),
                "wr_nim": b.get("wr"),
            }
        )
    out.sort(key=lambda x: float(x.get("lift") or 0), reverse=True)
    return out


async def async_main(args: argparse.Namespace) -> int:
    require_nvidia_api_key()
    print(">> NVIDIA key OK · refrescando catálogo de modelos…", flush=True)
    try:
        cached = cache_models(max_age_s=3600)
        ids = [m["id"] for m in (cached.get("models") or []) if m.get("id")]
        fast = pick_fast_models(ids)
        print(f"   primary={primary_model_id()} roster={fast[:4]}", flush=True)
    except Exception as e:
        print(f"   WARN models: {e} — sigo con primary", flush=True)

    if args.phase in ("scout", "all"):
        rows = await phase_scout(
            sessions=args.sessions,
            minutes=args.minutes,
            capitals=[float(args.scout_capital)],
        )
        path = _write_report("scout", rows)
        print(f"\nSCOUT -> {path}", flush=True)
        if args.phase == "scout":
            w = json.loads(path.read_text(encoding="utf-8")).get("winner")
            print("WINNER scout:", json.dumps(w, indent=2, ensure_ascii=False))
            return 0
        scout_rows = rows
    else:
        scout_path = OUT / "scout_latest.json"
        if not scout_path.is_file():
            print("FAIL: no scout_latest.json - corre --phase scout primero", flush=True)
            return 2
        scout_rows = json.loads(scout_path.read_text(encoding="utf-8")).get("ranked") or []

    finals = await phase_finals(
        scout_rows,
        sessions=args.final_sessions or max(args.sessions, 2),
        minutes=args.final_minutes or max(args.minutes, 3.0),
    )
    # Combinar scout+finals para leaderboard global
    merged = scout_rows + finals
    path = _write_report(
        "finals",
        finals,
        extra={
            "merged_top5": sorted(
                merged, key=lambda x: float(x.get("score") or -99), reverse=True
            )[:5]
        },
    )
    rep = json.loads(path.read_text(encoding="utf-8"))
    print(f"\nFINALS -> {path}", flush=True)
    print("WINNER:", json.dumps(rep.get("winner"), indent=2, ensure_ascii=False))
    print("NIM lift top:", json.dumps((rep.get("nim_vs_rules") or [])[:5], indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Sim live-exact tournament + NIM A/B")
    ap.add_argument("--phase", choices=("scout", "finals", "all"), default="all")
    ap.add_argument("--sessions", type=int, default=2, help="sesiones scout")
    ap.add_argument("--minutes", type=float, default=2.5, help="minutos scout")
    ap.add_argument("--final-sessions", type=int, default=2)
    ap.add_argument("--final-minutes", type=float, default=3.0)
    ap.add_argument("--scout-capital", type=float, default=10.0)
    args = ap.parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
