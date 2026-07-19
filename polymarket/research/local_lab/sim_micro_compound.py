#!/usr/bin/env python3
"""Sim CLOB real + dinero ficticio: compound micro 1–2€ (1 línea).

Itera sesiones, reinvierte ganancias, para si racha/DD. Compara vs scale.

    python3 -m polymarket.research.local_lab.sim_micro_compound \
      --rounds 10 --minutes 6 --start 2.0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.micro_compound import (
    HARD_CAP_USDC,
    MicroState,
    apply_round_result,
    max_affordable_price,
    recommend_path,
    session_capital,
)
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "sim_micro_compound"

MIN_WR = 0.80
MIN_DECISIVE = 6


def _force_dry(virt: float) -> dict[str, str]:
    prev = {
        "POLY_LIVE_ARMED": os.environ.get("POLY_LIVE_ARMED", "0"),
        "POLY_LIVE_DRY_RUN": os.environ.get("POLY_LIVE_DRY_RUN", "1"),
        "POLY_LIVE_MAX_CAPITAL_USDC": os.environ.get("POLY_LIVE_MAX_CAPITAL_USDC", "5"),
        "POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC": os.environ.get(
            "POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC", ""
        ),
        "POLY_LIVE_DRY_SMOKE_POST": os.environ.get("POLY_LIVE_DRY_SMOKE_POST", "0"),
        "NVIDIA_NIM_MODE": os.environ.get("NVIDIA_NIM_MODE", ""),
        "NVIDIA_NIM_GRIND": os.environ.get("NVIDIA_NIM_GRIND", ""),
    }
    os.environ["POLY_LIVE_ARMED"] = "1"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    os.environ["POLY_LIVE_DRY_SMOKE_POST"] = "0"
    os.environ["POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC"] = str(virt)
    os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = str(max(virt, HARD_CAP_USDC))
    # Micro: path determinista (fast) — evita starve por nim_error/timeout.
    os.environ["NVIDIA_NIM_MODE"] = "fast"
    os.environ["NVIDIA_NIM_GRIND"] = "0"
    return prev


def _restore(prev: dict[str, str]) -> None:
    for k, v in prev.items():
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    # no dejar ARMED real accidentalmente


async def _run_session(
    *,
    capital: float,
    minutes: float,
    base_cfg: dict,
    out_dir: Path,
    round_id: int,
) -> dict:
    from polymarket.research.local_lab.live_maker import run_live_session

    cfg = deepcopy(base_cfg)
    cfg["initial_capital_usdc"] = float(capital)
    cfg["max_notional_per_side_usdc"] = float(capital)
    cfg["max_inventory_usdc"] = float(capital)
    # Precio max operable con 5 shares
    px_max = max_affordable_price(capital)
    cfg["max_quote_mid"] = min(float(cfg.get("max_quote_mid") or 0.48), px_max + 0.08)
    cfg["demo_label"] = f"micro2_r{round_id}_c{capital:.2f}"
    path = out_dir / f"cfg_r{round_id:02d}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    # Virtual balance = capital (realista para micro)
    os.environ["POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC"] = str(max(capital, 2.0))
    os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = str(max(capital, HARD_CAP_USDC))
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    sid = f"micro2_r{round_id}_{stamp}"
    print(
        f">>> MICRO r={round_id} capital={capital:.2f} px_max≈{px_max:.2f}",
        flush=True,
    )
    report = await run_live_session(
        minutes=float(minutes),
        config_path=path,
        session_id=sid,
        strategy="maker_fusion",
        desk_line_id=1,
    )
    return {
        "ok": report.get("verdict") == "LIVE_DRY_RUN",
        "net": float(report.get("net_session_usdc") or 0),
        "fills": int(report.get("fills") or 0),
        "residual": float(report.get("inventory_residual") or 0),
        "strategy_id": report.get("strategy_id"),
        "session_dir": report.get("session_dir"),
        "coord_blocks": int(report.get("coord_blocks") or 0),
    }


async def async_main(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    base = json.loads(
        (POLY / "config" / args.config).read_text(encoding="utf-8")
    )
    start = float(args.start)
    state = MicroState(bankroll=start, peak=start, start_bankroll=start)

    prev = _force_dry(max(start * 3, 10.0))
    rows: list[dict] = []
    try:
        for r in range(1, int(args.rounds) + 1):
            if state.halted:
                print(f"HALT {state.halt_reason}", flush=True)
                break
            cap = session_capital(state, hard_cap=float(args.hard_cap))
            if cap < 1.25:
                if state.cooldown_left > 0:
                    apply_round_result(state, net=0.0, fills=0, start_capital=0.0)
                    print(f"COOLDOWN skip round {r}", flush=True)
                    continue
                state.halted = True
                state.halt_reason = "capital_too_small"
                break
            row = await _run_session(
                capital=cap,
                minutes=float(args.minutes),
                base_cfg=base,
                out_dir=OUT,
                round_id=r,
            )
            apply_round_result(
                state, net=row["net"], fills=row["fills"], start_capital=cap
            )
            row["bankroll_after"] = state.bankroll
            row["round"] = r
            rows.append(row)
            print(
                f"<<< r={r} net={row['net']:+.2f} fills={row['fills']} "
                f"bank={state.bankroll:.2f} wr={state.to_dict()['wr']}",
                flush=True,
            )

        st = state.to_dict()
        decisive = st["wins"] + st["losses"]
        wr_ok = st["wr"] >= MIN_WR and decisive >= MIN_DECISIVE
        pnl_ok = st["pnl_total"] > 0
        residual_ok = all(abs(float(r.get("residual") or 0)) < 0.01 for r in rows)
        parity_ok = all(r.get("strategy_id") == "maker_fusion" for r in rows) if rows else False

        # Comparativa caminos (métricas de diseño + resultado micro)
        comparison = {
            "paths": [
                {
                    "id": "micro2_single",
                    "label": "1 línea · 2€ compound",
                    "safer": True,
                    "collision_risk": 0.0,
                    "wr": st["wr"],
                    "pnl": st["pnl_total"],
                    "pioneer": "reinversión + kill DD/racha + precio acotado a floor CLOB",
                },
                {
                    "id": "micro5_single",
                    "label": "1 línea · 5€ fijo",
                    "safer": True,
                    "collision_risk": 0.0,
                    "wr": None,
                    "pnl": None,
                    "pioneer": "mínimo CLOB cómodo; menos reinversión agresiva",
                },
                {
                    "id": "scale_parallel",
                    "label": "2–4 líneas · 25€ scale",
                    "safer": False,
                    "collision_risk": 0.85,
                    "wr": None,
                    "pnl": None,
                    "pioneer": "más PnL teórico pero colisión; NO para 1–2€",
                },
            ]
        }
        rec = recommend_path(comparison)

        # Cert micro: WR + PnL>0 + residual0 + paridad fusion
        certified = bool(wr_ok and pnl_ok and residual_ok and parity_ok)

        report = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "env": "SIM_CLOB_FICTIONAL_MICRO2",
            "config": args.config,
            "start_usdc": float(args.start),
            "rounds_planned": int(args.rounds),
            "minutes": float(args.minutes),
            "state": st,
            "sessions": rows,
            "bars": {"min_wr": MIN_WR, "min_decisive": MIN_DECISIVE},
            "wr_ok": wr_ok,
            "pnl_ok": pnl_ok,
            "residual_ok": residual_ok,
            "parity_ok": parity_ok,
            "comparison": comparison,
            "recommendation": rec,
            "certified": certified,
            "verdict": (
                "MICRO2_CERTIFIED" if certified else "MICRO2_NOT_CERTIFIED"
            ),
            "operator_next": (
                "MICRO2 listo: dry 30–45m con capital 2→5, 1 línea, cheap_side. "
                "Luego DRY_RUN=0 MAX_CAPITAL=2..5. NO paralelo."
                if certified
                else "Seguir rondas o subir start=2.5 si starve por mid alto (5sh×px>2)."
            ),
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = OUT / f"micro_{stamp}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        (OUT / "micro_latest.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps({
            "verdict": report["verdict"],
            "state": {k: st[k] for k in (
                "bankroll", "wins", "losses", "wr", "pnl_total", "halted", "halt_reason"
            )},
            "recommendation": rec,
            "operator_next": report["operator_next"],
        }, indent=2), flush=True)
        print(f"REPORT -> {path}", flush=True)
        return 0 if certified else 1
    finally:
        _restore(prev)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="maker_demo_promo_pulse_micro2.json")
    ap.add_argument("--start", type=float, default=2.0)
    ap.add_argument("--hard-cap", type=float, default=5.0)
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--minutes", type=float, default=6.0)
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
