"""Política de gates live: SAFE por defecto, checklist dry, mínimos de caja.

Fase A/B/D del plan de situación — no reabrir real sin checklist + depósito.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
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

# Mínimo para REAL: por defecto ~1 pUSD (notional CLOB). Override: POLY_LIVE_MIN_BALANCE_PUSD.
def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def min_real_balance_pusd() -> float:
    """Saldo mínimo para REAL (env POLY_LIVE_MIN_BALANCE_PUSD, default 1.0)."""
    return _env_float("POLY_LIVE_MIN_BALANCE_PUSD", 1.0)


# Compat: valor por defecto documentado (la gate usa min_real_balance_pusd()).
MIN_REAL_BALANCE_PUSD = 1.0
MIN_REAL_CAPITAL = 1.0
# CLOB floor = 5 shares → notional típico ~1–3.5 USDC; techo sesión micro = 5.
MAX_REAL_CAPITAL = 5.0
MAX_SESSION_LOSS_USDC = 0.40
# Micro5 edge-validation: cupo diario amplio para recolectar ≥20 limpias sin
# tumbar el día por cohortes de pérdidas mecánicas ya corregidas (2026-07-20).
MAX_DAY_LOSS_USDC = 5.0
DRY_SESSIONS_REQUIRED = 10
GEOBLOCK_URL = "https://polymarket.com/api/geoblock"


def day_loss_disabled() -> bool:
    """POLY_LIVE_DAY_LOSS_DISABLE=1 → no aplicar tope diario (MAX_DAY_LOSS se conserva)."""
    return _flag("POLY_LIVE_DAY_LOSS_DISABLE", "0")


@dataclass(frozen=True)
class GeoBlockStatus:
    blocked: bool
    ip: str | None = None
    country: str | None = None
    region: str | None = None
    error: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def ok_to_trade(self) -> bool:
        return (not self.blocked) and self.error is None


def check_geoblock(*, timeout_s: float = 8.0) -> GeoBlockStatus:
    """Consulta el endpoint oficial de geoblock antes de postear órdenes reales.

    EE.UU. (y otras jurisdicciones) rechazan POST /order con 403. Fallar aquí
    evita sesiones de 15 min con señales OK pero 0 fills.
    """
    if _flag("POLY_LIVE_SKIP_GEOBLOCK", "0"):
        return GeoBlockStatus(blocked=False, error=None)
    try:
        req = urllib.request.Request(
            GEOBLOCK_URL,
            headers={"User-Agent": "polymarket-local-lab/1.0", "Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        raw = json.loads(body) if body.strip() else {}
        if not isinstance(raw, dict):
            return GeoBlockStatus(blocked=True, error="geoblock_bad_payload", raw={"body": body[:200]})
        blocked = bool(raw.get("blocked"))
        return GeoBlockStatus(
            blocked=blocked,
            ip=str(raw.get("ip") or "") or None,
            country=str(raw.get("country") or "") or None,
            region=str(raw.get("region") or "") or None,
            raw=raw,
        )
    except urllib.error.HTTPError as e:
        # Algunos edges responden 403 al propio geoblock desde IPs US — tratar como blocked.
        if int(getattr(e, "code", 0) or 0) == 403:
            return GeoBlockStatus(
                blocked=True,
                error="geoblock_http_403",
                country="US?",
            )
        return GeoBlockStatus(blocked=True, error=f"geoblock_http_{e.code}")
    except Exception as e:
        return GeoBlockStatus(blocked=True, error=f"{type(e).__name__}: {e}")


def geoblock_blocks_real() -> tuple[bool, str]:
    """True, msg si NO se puede operar REAL desde esta IP."""
    st = check_geoblock()
    if st.ok_to_trade:
        return False, "ok"
    where = ",".join(x for x in (st.country, st.region) if x) or "?"
    ip = st.ip or "?"
    detail = st.error or "blocked=true"
    return (
        True,
        f"GEOBLOCK ip={ip} where={where} ({detail}). "
        "Polymarket rechaza órdenes desde esta región — lanza REAL desde egress permitido "
        "(docs: eu-west-1 / jurisdicción no restringida). No usar VPN para evadir ToS.",
    )


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
    if day_loss_disabled():
        return False
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
    else:
        min_bal = min_real_balance_pusd()
        if bal + 1e-9 < min_bal:
            can_real = False
            blockers.append(
                f"Saldo {bal:.2f} pUSD < mínimo {min_bal:.2f} pUSD para live real"
            )
    if (not day_loss_disabled()) and day_pnl <= -MAX_DAY_LOSS_USDC:
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
    blocked, geo_msg = geoblock_blocks_real()
    if blocked:
        return False, geo_msg
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
    if "GEOBLOCK" in u or "Trading restricted in your region" in u:
        return "geoblock"
    if "FILL BUY" in u and "POST_ERR" in u and "balance" in u.lower():
        return "fill_exit_balance"
    return None
