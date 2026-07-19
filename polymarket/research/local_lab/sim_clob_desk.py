#!/usr/bin/env python3
"""Simulación CLOB 100% real (libros/red) con dinero FICTICIO — sin paper.

Anti-colisión: mutex_market | window_slot | ensemble_role
Barra: WR≥80% sobre sesiones dry con fill, PnL escalado.

    POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC=50 \\
    python3 -m polymarket.research.local_lab.sim_clob_desk \\
      --rounds 6 --minutes 8 --lines 2 --mode mutex_market
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.desk_coordinator import (
    coordinator_stats,
    effective_breadth,
    reset_coordinator,
)
from polymarket.research.local_lab.desk_risk import forecast_pnl
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "sim_clob_desk"

MIN_WR = 0.80
MIN_DECISIVE = 8
MIN_PNL = 1.00  # escala: ≥1 USDC en batería sim (no céntimos)


def _force_dry_virtual(*, capital: float) -> dict[str, str]:
    prev = {
        "POLY_LIVE_ARMED": os.environ.get("POLY_LIVE_ARMED", "0"),
        "POLY_LIVE_DRY_RUN": os.environ.get("POLY_LIVE_DRY_RUN", "1"),
        "POLY_LIVE_MAX_CAPITAL_USDC": os.environ.get("POLY_LIVE_MAX_CAPITAL_USDC", "5"),
        "POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC": os.environ.get(
            "POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC", ""
        ),
        "POLY_LIVE_DRY_SMOKE_POST": os.environ.get("POLY_LIVE_DRY_SMOKE_POST", "0"),
        "POLY_DESK_COORD_MODE": os.environ.get("POLY_DESK_COORD_MODE", ""),
    }
    virt = max(capital * 1.2, 50.0)
    os.environ["POLY_LIVE_ARMED"] = "1"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    os.environ["POLY_LIVE_DRY_SMOKE_POST"] = "0"
    os.environ["POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC"] = str(virt)
    os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = str(max(capital, virt))
    return prev


def _restore(prev: dict[str, str]) -> None:
    for k, v in prev.items():
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    print("SAFE restored after sim_clob_desk", flush=True)


def _role_cfg(base: dict, *, line_id: int, mode: str) -> dict:
    cfg = deepcopy(base)
    cfg["desk_coord_enable"] = True
    cfg["desk_coord_mode"] = mode
    cfg["desk_cluster_lines"] = int(base.get("desk_cluster_lines") or 2)
    if mode == "ensemble_role":
        # System diversification: roles distintos (Aussie Turtles / ensemble)
        roles = ("pulse", "follow")
        role = roles[(line_id - 1) % len(roles)]
        cfg["desk_role"] = role
        if role == "pulse":
            cfg["fusion_enable_pulse"] = True
            cfg["fusion_enable_follow"] = False
        elif role == "follow":
            cfg["fusion_enable_pulse"] = False
            cfg["fusion_enable_follow"] = True
        cfg["demo_label"] = f"{base.get('demo_label', 'sim')}_{role}_L{line_id}"
    else:
        cfg["desk_role"] = "pulse"
        cfg["demo_label"] = f"{base.get('demo_label', 'sim')}_L{line_id}"
    return cfg


async def _one_line(
    *,
    line_id: int,
    minutes: float,
    cfg: dict,
    mode: str,
    stagger_s: float,
    out_cfgs: Path,
) -> dict:
    if stagger_s > 0 and line_id > 1:
        await asyncio.sleep(float(stagger_s) * (line_id - 1))
    from polymarket.research.local_lab.live_maker import run_live_session

    line_cfg = _role_cfg(cfg, line_id=line_id, mode=mode)
    path = out_cfgs / f"line_{line_id:02d}.json"
    path.write_text(json.dumps(line_cfg, indent=2), encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sid = f"sim_clob_L{line_id}_{stamp}"
    print(f">>> SIM LINE {line_id} mode={mode} role={line_cfg.get('desk_role')}", flush=True)
    report = await run_live_session(
        minutes=float(minutes),
        config_path=path,
        session_id=sid,
        strategy="maker_fusion",
        desk_line_id=line_id,
    )
    return {
        "line_id": line_id,
        "role": line_cfg.get("desk_role"),
        "ok": report.get("verdict") == "LIVE_DRY_RUN" and bool(report.get("dry_run")),
        "verdict": report.get("verdict"),
        "strategy_id": report.get("strategy_id"),
        "fills": int(report.get("fills") or 0),
        "net": float(report.get("net_session_usdc") or 0),
        "inventory_residual": float(report.get("inventory_residual") or 0),
        "coord_blocks": int(report.get("coord_blocks") or 0),
        "session_dir": report.get("session_dir"),
        "parity_ok": report.get("strategy_id") == "maker_fusion",
    }


def _agg(rows: list[dict]) -> dict:
    nets = [float(r.get("net") or 0) for r in rows if int(r.get("fills") or 0) > 0]
    wins = sum(1 for n in nets if n > 1e-9)
    losses = sum(1 for n in nets if n < -1e-9)
    flats = sum(1 for n in nets if abs(n) <= 1e-9)
    decisive = wins + losses
    wr = (wins / decisive) if decisive else 0.0
    total = sum(float(r.get("net") or 0) for r in rows)
    blocks = sum(int(r.get("coord_blocks") or 0) for r in rows)
    return {
        "sessions_with_fills": len(nets),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "decisive": decisive,
        "wr": round(wr, 4),
        "total_pnl": round(total, 4),
        "coord_blocks": blocks,
        "avg_net_filled": round(sum(nets) / len(nets), 4) if nets else 0.0,
    }


async def async_main(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cfg_path = POLY / "config" / args.config
    base = json.loads(cfg_path.read_text(encoding="utf-8"))
    capital = float(base.get("initial_capital_usdc") or 25)
    mode = args.mode
    os.environ["POLY_DESK_COORD_MODE"] = mode
    reset_coordinator()
    prev = _force_dry_virtual(capital=capital)
    history: list[dict] = []
    try:
        for rnd in range(1, int(args.rounds) + 1):
            print(f"\n===== SIM CLOB ROUND {rnd}/{args.rounds} mode={mode} =====", flush=True)
            round_dir = OUT / f"round_{rnd:02d}"
            round_dir.mkdir(parents=True, exist_ok=True)
            rows = list(
                await asyncio.gather(
                    *[
                        _one_line(
                            line_id=i + 1,
                            minutes=float(args.minutes),
                            cfg=base,
                            mode=mode,
                            stagger_s=float(args.stagger_s),
                            out_cfgs=round_dir,
                        )
                        for i in range(int(args.lines))
                    ]
                )
            )
            history.append({"round": rnd, "rows": rows, "agg": _agg(rows)})
            print("ROUND", rnd, history[-1]["agg"], flush=True)

        # Agregar todas las sesiones con fill
        all_rows = [r for h in history for r in h["rows"]]
        final = _agg(all_rows)
        coord = coordinator_stats()
        n_eff = effective_breadth(int(args.lines), 0.85)
        collision_proxy = 0.0
        if int(coord.get("stats", {}).get("block") or 0) + int(
            coord.get("stats", {}).get("allow") or 0
        ) > 0:
            b = int(coord["stats"]["block"])
            a = int(coord["stats"]["allow"])
            collision_proxy = b / (a + b)

        wr_ok = float(final["wr"]) >= MIN_WR and int(final["decisive"]) >= MIN_DECISIVE
        pnl_ok = float(final["total_pnl"]) >= MIN_PNL
        dry_ok = all(r.get("ok") and r.get("parity_ok") for r in all_rows)
        residual_ok = all(abs(float(r.get("inventory_residual") or 0)) < 0.01 for r in all_rows)
        certified = bool(wr_ok and pnl_ok and dry_ok and residual_ok)

        fc = forecast_pnl(
            hours=1.0,
            lines=1,
            wr=float(final["wr"] or 0.8),
            avg_win=max(0.15, float(final.get("avg_net_filled") or 0.15)),
            avg_loss=-max(0.12, abs(float(final.get("avg_net_filled") or 0.12))),
            capital_scale=float(capital) / 10.0,
            rho=0.85,
        )

        report = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "env": "SIM_CLOB_FICTIONAL_MONEY",
            "config": args.config,
            "mode": mode,
            "lines": int(args.lines),
            "rounds": int(args.rounds),
            "minutes": float(args.minutes),
            "virtual_balance": os.environ.get("POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC"),
            "bars": {
                "min_wr": MIN_WR,
                "min_decisive": MIN_DECISIVE,
                "min_pnl": MIN_PNL,
            },
            "history": history,
            "final": final,
            "coordinator": coord,
            "n_eff": round(n_eff, 3),
            "collision_block_rate": round(collision_proxy, 4),
            "forecast_1h_scaled": fc,
            "wr_ok": wr_ok,
            "pnl_ok": pnl_ok,
            "dry_ok": dry_ok,
            "residual_ok": residual_ok,
            "certified": certified,
            "verdict": "SIM_CLOB_CERTIFIED" if certified else "SIM_CLOB_NOT_CERTIFIED",
            "operator_next": (
                "SIM_CLOB_CERTIFIED → dry operativo 45m → micro real capital=5..25 "
                "con DRY_RUN=0. Mantener mutex en paralelo."
                if certified
                else "Seguir rondas sim_clob_desk hasta WR≥80% decisive≥10 y PnL≥+1.50"
            ),
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = OUT / f"sim_{stamp}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        (OUT / "sim_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: report[k] for k in (
            "verdict", "final", "collision_block_rate", "n_eff", "operator_next"
        )}, indent=2), flush=True)
        print(f"REPORT -> {path}", flush=True)
        return 0 if certified else 1
    finally:
        _restore(prev)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="maker_demo_promo_pulse_sim_scale.json")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--minutes", type=float, default=8.0)
    ap.add_argument("--lines", type=int, default=2)
    ap.add_argument("--stagger-s", type=float, default=20.0)
    ap.add_argument(
        "--mode",
        default="mutex_market",
        choices=("mutex_market", "window_slot", "ensemble_role"),
    )
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
