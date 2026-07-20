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


def _notify_stopped_no_funds(*, bal: float, min_balance: float) -> None:
    """Aviso: desk parado por saldo insuficiente (no seguir en negativo)."""
    try:
        from polymarket.src.notify.mailer import send_email
        from polymarket.src.notify.trial_email import build_simple_banner_email

        title = "DESK PARADO — sin fondos"
        body = (
            f"poly-desk-forever se ha DETENIDO para no operar en negativo.\n\n"
            f"Saldo CLOB: {bal:.4f} pUSD\n"
            f"Mínimo requerido: {min_balance:.2f} pUSD\n\n"
            f"No se lanzarán más sesiones REAL hasta que recargues y hagas:\n"
            f"  pm2 start poly-desk-forever\n"
        )
        _, html = build_simple_banner_email(title=title, body=body)
        r = send_email(
            subject=f"[Poly Desk] PARADO sin fondos · saldo {bal:.2f} pUSD",
            body_text=body,
            body_html=html,
        )
        print(f"EMAIL_STOP_NO_FUNDS ok={r.get('ok')} err={r.get('error')}", flush=True)
    except Exception as e:
        print(f"EMAIL_STOP_ERR {type(e).__name__}: {e}", flush=True)


def _halt_no_funds(*, bal: float, min_balance: float, loops: int) -> int:
    print(
        f"STOP_NO_FUNDS bal={bal:.4f} < min={min_balance:.2f} — "
        "SAFE + exit (no más trading)",
        flush=True,
    )
    _force_safe()
    _cancel_all()
    _write_hb(
        status="stopped_no_funds",
        loops=loops,
        balance=bal,
        min_balance=min_balance,
        reason="insufficient_balance",
    )
    _notify_stopped_no_funds(bal=bal, min_balance=min_balance)
    _STOP.set()
    return 0


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
        # Sin dinero suficiente → PARAR del todo (no sleep infinito / no negativos).
        if bal + 1e-9 < float(args.min_balance):
            return _halt_no_funds(
                bal=float(bal),
                min_balance=float(args.min_balance),
                loops=loops,
            )

        cap = min(float(args.capital), float(bal) * 0.98)
        # Floor CLOB / política micro5
        if cap + 1e-9 < float(args.min_balance):
            return _halt_no_funds(
                bal=float(bal),
                min_balance=float(args.min_balance),
                loops=loops,
            )

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

        bal_after = _balance()
        _write_hb(status="pause", loops=loops, last_rc=rc, balance=bal_after)
        if bal_after is not None and bal_after + 1e-9 < float(args.min_balance):
            return _halt_no_funds(
                bal=float(bal_after),
                min_balance=float(args.min_balance),
                loops=loops,
            )
        print(f"PAUSE {args.pause_s}s antes de la siguiente (rc={rc})", flush=True)
        _STOP.wait(float(args.pause_s))

    _force_safe()
    _cancel_all()
    _write_hb(status="stopped", loops=loops)
    print("DESK_FOREVER stopped SAFE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
