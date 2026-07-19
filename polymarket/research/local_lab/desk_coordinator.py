"""Coordinador de desk anti-colisión (exposición compartida entre líneas).

Teoría aplicada (desks / literatura pública):
- System diversification (Aussie Turtles): lógicas distintas, no clones del mismo DNA.
- Cluster sizing (D&T Systems): ρ>0.8 ⇒ una sola unidad de riesgo.
- Portfolio heat veto (ProfitLogic): capa central que bloquea entradas correlacionadas.
- Cross-filter (MQL5 Part 7): no abrir si ya hay exposición misma dirección/mercado.
- Effective breadth N_eff = N/(1+(N-1)ρ) (MarketMaker.cc / design-effect).

Modos:
  mutex_market  — solo 1 línea con inventario/claim por market_id
  window_slot   — líneas en ventanas 5m alternas (par/impar)
  ensemble_role — roles pulse|follow|shadow (activación descorrelacionada)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
STATE_PATH = Path(
    os.getenv("POLY_DESK_COORD_PATH")
    or (POLY / "data_local" / "local_lab" / "desk_coordinator.json")
)


def effective_breadth(n: int, rho: float = 0.85) -> float:
    """N_eff = N / (1+(N-1)ρ) — design-effect / signal breadth."""
    n = max(1, int(n))
    rho = max(0.0, min(0.99, float(rho)))
    return n / (1.0 + (n - 1) * rho)


def size_scale_for_cluster(n: int, rho: float = 0.85) -> float:
    """Escala de size por línea si N clones están correlacionados.

    Cluster de N con ρ alto se trata como 1 unidad → cada línea recibe
    size_scale = N_eff / N  (suma de riesgos ≈ 1 unidad efectiva).
    """
    n = max(1, int(n))
    return effective_breadth(n, rho) / n


@dataclass
class ClaimResult:
    ok: bool
    reason: str
    state: dict[str, Any]


def _load() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {"claims": {}, "updated_utc": None, "stats": {"block": 0, "allow": 0}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"claims": {}, "updated_utc": None, "stats": {"block": 0, "allow": 0}}


def _save(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def reset_coordinator() -> None:
    _save({"claims": {}, "updated_utc": None, "stats": {"block": 0, "allow": 0}})


def _window_slot_ok(line_id: int, window_start_ns: int | None) -> bool:
    if window_start_ns is None:
        return True
    # Ventanas BTC 5m: index = floor(start / 300s)
    idx = int(window_start_ns // int(300e9))
    return (idx % 2) == ((int(line_id) - 1) % 2)


def try_claim(
    *,
    line_id: int,
    market_id: str,
    direction: str,
    mode: str = "mutex_market",
    role: str = "pulse",
    window_start_ns: int | None = None,
    ttl_s: float = 280.0,
) -> ClaimResult:
    """Intenta reclamar exposición. Si ok=False, la línea no debe entrar."""
    mode = (mode or "mutex_market").strip().lower()
    mid = str(market_id or "")
    if not mid:
        return ClaimResult(True, "no_market", _load())

    state = _load()
    claims: dict[str, Any] = state.setdefault("claims", {})
    stats = state.setdefault("stats", {"block": 0, "allow": 0})
    now = time.time()

    # Expirar claims viejos
    dead = [k for k, v in claims.items() if float(v.get("until", 0)) < now]
    for k in dead:
        claims.pop(k, None)

    if mode == "window_slot" and not _window_slot_ok(line_id, window_start_ns):
        stats["block"] = int(stats.get("block") or 0) + 1
        _save(state)
        return ClaimResult(False, "window_slot_skip", state)

    # Ensemble: no bloquea market, pero registra role (filtro blando en live_maker via cfg)
    if mode == "ensemble_role":
        key = f"{mid}:{direction}"
        existing = claims.get(key)
        if existing and int(existing.get("line_id") or -1) != int(line_id):
            # Misma dirección en mismo market → veto (cross-filter)
            stats["block"] = int(stats.get("block") or 0) + 1
            _save(state)
            return ClaimResult(False, "ensemble_same_dir", state)
        claims[key] = {
            "line_id": int(line_id),
            "direction": direction,
            "role": role,
            "until": now + float(ttl_s),
        }
        stats["allow"] = int(stats.get("allow") or 0) + 1
        _save(state)
        return ClaimResult(True, "ensemble_ok", state)

    # mutex_market (default): 1 claim por market
    key = f"m:{mid}"
    existing = claims.get(key)
    if existing and int(existing.get("line_id") or -1) != int(line_id):
        stats["block"] = int(stats.get("block") or 0) + 1
        _save(state)
        return ClaimResult(False, "mutex_held", state)

    claims[key] = {
        "line_id": int(line_id),
        "direction": direction,
        "role": role,
        "until": now + float(ttl_s),
    }
    stats["allow"] = int(stats.get("allow") or 0) + 1
    _save(state)
    return ClaimResult(True, "mutex_ok", state)


def release(*, line_id: int, market_id: str) -> None:
    state = _load()
    claims = state.get("claims") or {}
    mid = str(market_id or "")
    for key in list(claims.keys()):
        v = claims[key]
        if int(v.get("line_id") or -1) == int(line_id) and mid in key:
            claims.pop(key, None)
    state["claims"] = claims
    _save(state)


def coordinator_stats() -> dict[str, Any]:
    return _load()
