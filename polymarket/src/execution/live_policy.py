"""Política de gates live: SAFE por defecto, checklist dry, mínimos de caja.

Fase A/B/D del plan de situación — no reabrir real sin checklist + depósito.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
LAB = POLY / "data_local" / "local_lab"
CHECKLIST_PATH = LAB / "live_checklist.json"
DAY_PNL_PATH = LAB / "live_day_pnl.json"

# Plan: no live_real con saldo bajo; depósito mínimo recomendado
MIN_REAL_BALANCE_PUSD = 5.0
MIN_REAL_CAPITAL = 1.0
# CLOB floor = 5 shares → notional típico ~2–3.5 USDC; micro real viable = 5.
MAX_REAL_CAPITAL = 5.0
MAX_SESSION_LOSS_USDC = 0.40
MAX_DAY_LOSS_USDC = 1.0
DRY_SESSIONS_REQUIRED = 10


@dataclass(frozen=True)
class LiveReadiness:
    can_dry: bool
    can_real: bool
    checklist_ok: bool
    dry_sessions: int
    balance_pusd: float | None
    blockers: list[str]
    day_pnl: float
    min_real_balance: float = MIN_REAL_BALANCE_PUSD


def _flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip() == "1"


def checklist_path() -> Path:
    return Path(os.getenv("POLY_LIVE_CHECKLIST_PATH") or CHECKLIST_PATH)


def load_checklist() -> dict[str, Any]:
    path = checklist_path()
    if not path.is_file():
        return {
            "ok": False,
            "dry_sessions_clean": 0,
            "required": DRY_SESSIONS_REQUIRED,
            "updated_utc": None,
            "notes": "Sin checklist — ejecuta dry_e2e_batch / tests Fase B.",
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "dry_sessions_clean": 0, "required": DRY_SESSIONS_REQUIRED}
    return raw if isinstance(raw, dict) else {"ok": False}


def save_checklist(data: dict[str, Any]) -> Path:
    path = checklist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **data,
        "required": int(data.get("required") or DRY_SESSIONS_REQUIRED),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    clean = int(payload.get("dry_sessions_clean") or 0)
    need = int(payload["required"])
    payload["ok"] = bool(payload.get("ok")) or clean >= need
    if clean >= need:
        payload["ok"] = True
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_day_pnl() -> dict[str, Any]:
    if not DAY_PNL_PATH.is_file():
        return {"date": date.today().isoformat(), "pnl": 0.0, "sessions": 0}
    try:
        raw = json.loads(DAY_PNL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"date": date.today().isoformat(), "pnl": 0.0, "sessions": 0}
    if raw.get("date") != date.today().isoformat():
        return {"date": date.today().isoformat(), "pnl": 0.0, "sessions": 0}
    return raw


def record_session_pnl(net: float) -> dict[str, Any]:
    """Acumula PnL del día (para kill diario)."""
    cur = load_day_pnl()
    cur["pnl"] = round(float(cur.get("pnl") or 0) + float(net), 4)
    cur["sessions"] = int(cur.get("sessions") or 0) + 1
    cur["date"] = date.today().isoformat()
    DAY_PNL_PATH.parent.mkdir(parents=True, exist_ok=True)
    DAY_PNL_PATH.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return cur


def day_loss_breached(extra_net: float = 0.0) -> bool:
    pnl = float(load_day_pnl().get("pnl") or 0) + float(extra_net)
    return pnl <= -MAX_DAY_LOSS_USDC


def force_safe_env(upsert_env) -> None:
    """upsert_env(key, value) — pone SAFE en .env + os.environ."""
    upsert_env("POLY_LIVE_ARMED", "0")
    upsert_env("POLY_LIVE_DRY_RUN", "1")


def evaluate_readiness(*, balance_pusd: float | None, dry_run: bool) -> LiveReadiness:
    cl = load_checklist()
    dry_n = int(cl.get("dry_sessions_clean") or 0)
    need = int(cl.get("required") or DRY_SESSIONS_REQUIRED)
    checklist_ok = bool(cl.get("ok")) and dry_n >= need
    day = load_day_pnl()
    day_pnl = float(day.get("pnl") or 0)
    blockers: list[str] = []

    can_dry = True
    if dry_run is False:
        # evaluating real path
        pass

    allow_bypass = _flag("POLY_LIVE_BYPASS_CHECKLIST", "0")
    bal = balance_pusd

    can_real = True
    if not allow_bypass and not checklist_ok:
        can_real = False
        blockers.append(
            f"Checklist dry incompleto ({dry_n}/{need}). "
            "Corre: python -m polymarket.research.local_lab.dry_e2e_batch"
        )
    if bal is None:
        can_real = False
        blockers.append("No se pudo leer saldo pUSD")
    elif bal + 1e-9 < MIN_REAL_BALANCE_PUSD:
        can_real = False
        blockers.append(
            f"Saldo {bal:.2f} pUSD < mínimo {MIN_REAL_BALANCE_PUSD:.0f} pUSD para live real"
        )
    if day_pnl <= -MAX_DAY_LOSS_USDC:
        can_real = False
        blockers.append(f"Pérdida diaria {day_pnl:.2f} ≤ -{MAX_DAY_LOSS_USDC:.0f} — SAFE")

    return LiveReadiness(
        can_dry=True,
        can_real=can_real,
        checklist_ok=checklist_ok,
        dry_sessions=dry_n,
        balance_pusd=bal,
        blockers=blockers,
        day_pnl=day_pnl,
    )


def validate_real_start(capital: float, balance_pusd: float | None) -> tuple[bool, str]:
    ready = evaluate_readiness(balance_pusd=balance_pusd, dry_run=False)
    if not ready.can_real:
        return False, "; ".join(ready.blockers) or "Live real bloqueado por política"
    cap = float(capital)
    if cap + 1e-9 < MIN_REAL_CAPITAL:
        return False, f"Capital live real mínimo {MIN_REAL_CAPITAL:.1f}€"
    if cap > MAX_REAL_CAPITAL + 1e-9:
        return (
            False,
            f"Capital live real máximo {MAX_REAL_CAPITAL:.1f}€/sesión (protocolo Fase D)",
        )
    if balance_pusd is not None and cap > float(balance_pusd) + 0.05:
        return False, f"Capital {cap:.2f} > saldo {balance_pusd:.2f} pUSD"
    return True, "ok"


def kill_line_reason(line: str) -> str | None:
    """Si el log indica peligro → razón de stop (None = ok)."""
    u = line or ""
    if "DUST_STUCK" in u:
        return "dust_stuck"
    if "FLATTEN_WRONG_TOKEN" in u:
        return "wrong_token"
    if "KILL_SESSION" in u:
        return "kill_session"
    if "KILL_DAY" in u:
        return "kill_day"
    if "FILL BUY" in u and "POST_ERR" in u and "balance" in u.lower():
        return "fill_exit_balance"
    return None
