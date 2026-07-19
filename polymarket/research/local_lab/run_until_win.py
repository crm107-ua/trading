#!/usr/bin/env python3
"""Lanza micro 2.5€ en bucle hasta ganar (fill + PnL > 0).

- Si la IP está geobloqueada → NO gasta sesiones REAL inútiles; corre sim CLOB
  (dinero ficticio + feeds reales) hasta compound ganador.
- Si geoblock OK → lanza REAL micro25 y para al primer win limpio.

    python3 -m polymarket.research.local_lab.run_until_win --max-rounds 8 --minutes 12
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.execution.live_policy import check_geoblock, geoblock_blocks_real

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "until_win"


def _safe() -> None:
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"


def _bal() -> float | None:
    try:
        from polymarket.src.execution.clob_live import ClobLiveClient

        cli = ClobLiveClient()
        cli.connect()
        return float(cli.balance_collateral_usdc())
    except Exception as e:
        print(f"BAL_ERR {type(e).__name__}: {e}", flush=True)
        return None


async def _sim_until_win(*, rounds: int, minutes: float, start: float) -> dict:
    """Delega en sim_micro_compound (CLOB dry + virtual balance)."""
    cmd = [
        sys.executable,
        "-m",
        "polymarket.research.local_lab.sim_micro_compound",
        "--rounds",
        str(int(rounds)),
        "--minutes",
        str(float(minutes)),
        "--start",
        str(float(start)),
    ]
    print(f"SIM_CMD {' '.join(cmd)}", flush=True)
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(POLY.parent),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    lines: list[str] = []
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        s = line.decode("utf-8", errors="replace").rstrip()
        lines.append(s)
        print(s, flush=True)
    rc = await proc.wait()
    latest = POLY / "data_local" / "local_lab" / "sim_micro_compound" / "micro_latest.json"
    payload: dict = {}
    if latest.is_file():
        payload = json.loads(latest.read_text(encoding="utf-8"))
    st = payload.get("state") or {}
    start_b = float(payload.get("start_usdc") or start)
    end = float(st.get("bankroll") or start_b)
    wins = int(st.get("wins") or 0)
    sessions = payload.get("sessions") or []
    fills = sum(int(s.get("fills") or 0) for s in sessions)
    certified = bool(payload.get("certified") or payload.get("verdict") == "MICRO2_CERTIFIED")
    pnl = float(st.get("pnl_total") if st.get("pnl_total") is not None else round(end - start_b, 4))
    # Win = PnL>0 con al menos un fill, o certificación micro
    won = bool(certified or (pnl > 0 and fills > 0 and wins > 0))
    return {
        "mode": "sim_clob_fictional",
        "rc": rc,
        "elapsed_s": round(time.time() - t0, 1),
        "won": won,
        "pnl_usdc": pnl,
        "bankroll_start": start_b,
        "bankroll_end": end,
        "wins": wins,
        "fills": fills,
        "certified": certified,
        "verdict": payload.get("verdict"),
        "payload": payload,
        "tail": lines[-30:],
    }


async def _real_once(*, minutes: float) -> dict:
    bal0 = _bal()
    cmd = [
        sys.executable,
        "-m",
        "polymarket.research.local_lab.run_real_micro25",
        "--minutes",
        str(float(minutes)),
    ]
    print(f"REAL_CMD {' '.join(cmd)} bal0={bal0}", flush=True)
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(POLY.parent),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ},
    )
    assert proc.stdout is not None
    lines: list[str] = []
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        s = line.decode("utf-8", errors="replace").rstrip()
        lines.append(s)
        print(s, flush=True)
    rc = await proc.wait()
    _safe()
    latest = POLY / "data_local" / "local_lab" / "real_micro25" / "real_latest.json"
    payload: dict = {}
    if latest.is_file():
        payload = json.loads(latest.read_text(encoding="utf-8"))
    report = payload.get("report") or {}
    delta = payload.get("balance_delta")
    fills = int(report.get("fills") or 0)
    net = float(report.get("net_session_usdc") or 0)
    bal1 = _bal()
    won = bool(
        fills > 0
        and (
            (delta is not None and float(delta) > 0)
            or net > 0
            or (bal0 is not None and bal1 is not None and float(bal1) > float(bal0) + 0.01)
        )
        and not payload.get("danger")
    )
    return {
        "mode": "real_onchain",
        "rc": rc,
        "elapsed_s": round(time.time() - t0, 1),
        "won": won,
        "fills": fills,
        "net_session_usdc": net,
        "balance_before": bal0,
        "balance_after": bal1,
        "balance_delta": delta,
        "danger": payload.get("danger") or [],
        "abort": payload.get("abort"),
        "verdict": report.get("verdict"),
        "payload": payload,
        "tail": lines[-40:],
    }


async def async_main(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    _safe()
    # Micro fill-rate: reglas fast; NIM timeout no debe tumbar entradas.
    os.environ.setdefault("NVIDIA_NIM_MODE", "fast")
    if (os.environ.get("NVIDIA_NIM_MODE") or "").strip().lower() == "hybrid":
        # En until-win preferimos fills > NIM; override hybrid del .env.
        os.environ["NVIDIA_NIM_MODE"] = "fast"
    os.environ["NVIDIA_NIM_GRIND"] = "0"
    geo = check_geoblock()
    blocked, geo_msg = geoblock_blocks_real()
    print(
        f"GEO blocked={geo.blocked} ip={geo.ip} country={geo.country} "
        f"region={geo.region} err={geo.error}",
        flush=True,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    attempts: list[dict] = []
    won = False
    final: dict = {}

    if blocked:
        print(f"REAL imposible aquí: {geo_msg}", flush=True)
        print("→ Continuando en SIM CLOB (ficticio) hasta ganar.", flush=True)
        batches = max(1, int(args.sim_batches))
        for b in range(1, batches + 1):
            print(f"\n=== SIM BATCH {b}/{batches} ===", flush=True)
            final = await _sim_until_win(
                rounds=int(args.max_rounds),
                minutes=float(args.sim_minutes),
                start=float(args.start),
            )
            attempts.append(final)
            won = bool(final.get("won"))
            if won:
                break
            print(
                f"SIM batch {b} no-win pnl={final.get('pnl_usdc')} "
                f"fills={final.get('fills')} — reintento",
                flush=True,
            )
    else:
        for i in range(1, int(args.max_rounds) + 1):
            print(f"\n=== REAL ATTEMPT {i}/{args.max_rounds} ===", flush=True)
            one = await _real_once(minutes=float(args.minutes))
            attempts.append(one)
            if one.get("abort") and "GEOBLOCK" in str(one.get("abort")):
                print("Geoblock mid-run → fallback SIM", flush=True)
                final = await _sim_until_win(
                    rounds=max(4, int(args.max_rounds) - i + 1),
                    minutes=float(args.sim_minutes),
                    start=float(args.start),
                )
                attempts.append(final)
                won = bool(final.get("won"))
                break
            if one.get("won"):
                won = True
                final = one
                break
            # Pausa corta entre sesiones
            await asyncio.sleep(float(args.pause_s))
        else:
            final = attempts[-1] if attempts else {}

    out = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "geoblock": {
            "blocked": geo.blocked,
            "ip": geo.ip,
            "country": geo.country,
            "region": geo.region,
            "error": geo.error,
            "msg": geo_msg,
        },
        "won": won,
        "attempts": len(attempts),
        "final": {k: v for k, v in final.items() if k not in ("payload", "tail")},
        "history": [{k: v for k, v in a.items() if k not in ("payload", "tail")} for a in attempts],
    }
    path = OUT / f"until_win_{stamp}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    (OUT / "until_win_latest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2), flush=True)
    print(f"REPORT -> {path}", flush=True)
    _safe()
    return 0 if won else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-rounds", type=int, default=8)
    ap.add_argument("--sim-batches", type=int, default=4, help="reintentos SIM si no hay win")
    ap.add_argument("--minutes", type=float, default=12.0, help="minutos por sesión REAL")
    ap.add_argument("--sim-minutes", type=float, default=6.0, help="minutos por ronda SIM")
    ap.add_argument("--start", type=float, default=2.5, help="bankroll SIM inicial")
    ap.add_argument("--pause-s", type=float, default=5.0)
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
