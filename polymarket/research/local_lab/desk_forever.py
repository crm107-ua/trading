#!/usr/bin/env python3
"""Desk REAL infinito — 1 sesión tras otra hasta `pm2 stop`.

Cada 3h envía informe HTML a MAIL_TO (default caromamusic@gmail.com).

    python -m polymarket.research.local_lab.desk_forever
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
REPO = POLY.parent
LAB = POLY / "data_local" / "local_lab"
HEARTBEAT = LAB / "desk_forever_heartbeat.json"

_STOP = threading.Event()


def _force_safe() -> None:
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"


def _write_hb(**kw) -> None:
    LAB.mkdir(parents=True, exist_ok=True)
    cur = {}
    if HEARTBEAT.is_file():
        try:
            cur = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
    cur.update(kw)
    cur["ts_utc"] = datetime.now(timezone.utc).isoformat()
    HEARTBEAT.write_text(json.dumps(cur, indent=2), encoding="utf-8")


def _balance() -> float | None:
    try:
        from polymarket.src.execution.clob_live import ClobLiveClient

        cli = ClobLiveClient()
        cli.connect()
        return float(cli.balance_collateral_usdc())
    except Exception as e:
        print(f"BAL_ERR {type(e).__name__}: {e}", flush=True)
        return None


def _cancel_all() -> None:
    try:
        os.environ["POLY_LIVE_ARMED"] = "1"
        os.environ["POLY_LIVE_DRY_RUN"] = "0"
        from polymarket.src.execution.clob_live import ClobLiveClient

        cli = ClobLiveClient()
        cli.connect()
        print("CANCEL_ALL", cli.cancel_all(), flush=True)
    except Exception as e:
        print(f"CANCEL_ERR {type(e).__name__}: {e}", flush=True)
    finally:
        _force_safe()


def _report_worker(interval_s: float) -> None:
    # Primer informe a los ~2 min (smoke), luego cada interval_s
    if _STOP.wait(120):
        return
    while not _STOP.is_set():
        try:
            from polymarket.research.local_lab.pnl_report_email import send_report

            r = send_report(force=True)
            print(
                f"EMAIL_REPORT ok={r.get('ok')} to={r.get('to')} "
                f"day={r.get('day_pnl')} bal={r.get('balance')} err={r.get('error')}",
                flush=True,
            )
            _write_hb(last_email_ok=bool(r.get("ok")), last_email_err=r.get("error"))
        except Exception as e:
            print(f"EMAIL_ERR {type(e).__name__}: {e}", flush=True)
        if _STOP.wait(interval_s):
            break


def _run_one_session(
    *,
    capital: float,
    minutes: float,
    config: str,
    cwd: Path,
) -> int:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        sys.executable,
        "-m",
        "polymarket.research.local_lab.run_real_micro25",
        "--capital",
        str(capital),
        "--minutes",
        str(minutes),
        "--config",
        config,
    ]
    print(f"=== FOREVER SESSION start cfg={config} cap={capital} min={minutes} ===", flush=True)
    p = subprocess.run(cmd, cwd=str(cwd), env=env)
    print(f"=== FOREVER SESSION end code={p.returncode} ===", flush=True)
    return int(p.returncode)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=float, default=float(os.getenv("POLY_DESK_MINUTES") or 12))
    ap.add_argument(
        "--capital",
        type=float,
        default=float(os.getenv("POLY_DESK_CAPITAL") or os.getenv("POLY_LIVE_MAX_CAPITAL_USDC") or 5),
    )
    ap.add_argument(
        "--config",
        default=os.getenv("POLY_DESK_CONFIG")
        or os.getenv("POLY_LIVE_CONFIG")
        or "maker_demo_promo_pulse_micro5_scalp.json",
    )
    ap.add_argument(
        "--pause-s",
        type=float,
        default=float(os.getenv("POLY_DESK_PAUSE_S") or 45),
    )
    ap.add_argument(
        "--min-balance",
        type=float,
        default=float(os.getenv("POLY_DESK_MIN_BALANCE") or 5.0),
    )
    ap.add_argument(
        "--email-every-s",
        type=float,
        default=float(os.getenv("POLY_DESK_EMAIL_EVERY_S") or 3 * 3600),
    )
    args = ap.parse_args()

    # Quitar path de config tipo polymarket/config/...
    cfg = str(args.config).replace("\\", "/").split("/")[-1]

    def _sig(*_a):
        print("SIGNAL stop requested — fin tras sesión actual / espera", flush=True)
        _STOP.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    mail_to = os.getenv("MAIL_TO") or "caromamusic@gmail.com"
    os.environ.setdefault("MAIL_TO", mail_to)

    t = threading.Thread(
        target=_report_worker, args=(float(args.email_every_s),), daemon=True
    )
    t.start()
    print(
        f"DESK_FOREVER start cfg={cfg} capital={args.capital} minutes={args.minutes} "
        f"pause={args.pause_s}s email_every={args.email_every_s}s to={mail_to}",
        flush=True,
    )
    _write_hb(status="starting", loops=0, config=cfg, capital=args.capital)

    loops = 0
    while not _STOP.is_set():
        loops += 1
        bal = _balance()
        _write_hb(
            status="loop",
            loops=loops,
            balance=bal,
            config=cfg,
            capital=args.capital,
        )
        if bal is None:
            print("WAIT bal=None — reintento en 60s", flush=True)
            _STOP.wait(60)
            continue
        if bal + 1e-9 < float(args.min_balance):
            print(
                f"WAIT_BALANCE bal={bal:.4f} < min={args.min_balance} — sleep 120s",
                flush=True,
            )
            _write_hb(status="wait_balance", loops=loops, balance=bal)
            _STOP.wait(120)
            continue

        cap = min(float(args.capital), float(bal) * 0.98)
        # Floor CLOB / política micro5
        if cap + 1e-9 < 5.0 and float(args.min_balance) >= 5.0:
            print(f"WAIT_CAP capital_efectivo={cap:.2f} < 5 — sleep 120s", flush=True)
            _write_hb(status="wait_capital", loops=loops, balance=bal, capital_eff=cap)
            _STOP.wait(120)
            continue

        _cancel_all()
        _write_hb(status="trading", loops=loops, balance=bal, capital_eff=cap)
        try:
            rc = _run_one_session(
                capital=round(cap, 2),
                minutes=float(args.minutes),
                config=cfg,
                cwd=REPO,
            )
        except Exception as e:
            print(f"SESSION_ERR {type(e).__name__}: {e}", flush=True)
            rc = 99
        finally:
            _force_safe()
            _cancel_all()

        _write_hb(status="pause", loops=loops, last_rc=rc, balance=_balance())
        print(f"PAUSE {args.pause_s}s antes de la siguiente (rc={rc})", flush=True)
        _STOP.wait(float(args.pause_s))

    _force_safe()
    _cancel_all()
    _write_hb(status="stopped", loops=loops)
    print("DESK_FOREVER stopped SAFE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
