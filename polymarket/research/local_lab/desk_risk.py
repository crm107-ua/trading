"""Desk risk: presupuesto, correlación de líneas y previsión EV.

Diseñado para pulse@10 en BTC 5m — las líneas en el mismo mercado están
fuertemente correlacionadas; el PnL NO escala como N×.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Correlación empírica conservadora mismo mercado BTC 5m / mismo DNA.
DEFAULT_SAME_MARKET_RHO = 0.85

# Ladder micro real (USDC). Primer peldaño = 5 (mínimo CLOB-viable con 5 shares).
CAPITAL_LADDER_USDC: tuple[float, ...] = (5.0,)

# EV medido paper pulse@10 (sesión con fill, excl. outliers) — baseline.
# Se recalcula si hay métricas frescas.
DEFAULT_EV: dict[str, float] = {
    "wr": 0.83,
    "avg_win_usdc": 0.094,
    "avg_loss_usdc": -0.087,
    "fill_rate": 0.55,  # fracción de ventanas 5m con fill
    "sessions_per_hour": 12.0,  # ventanas 5m
}


@dataclass(frozen=True)
class RiskBudget:
    max_lines: int
    capital_per_line_usdc: float
    max_desk_notional_usdc: float
    max_session_loss_usdc: float
    max_day_loss_usdc: float
    rho: float
    effective_independent_lines: float
    stagger_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_lines": self.max_lines,
            "capital_per_line_usdc": self.capital_per_line_usdc,
            "max_desk_notional_usdc": round(self.max_desk_notional_usdc, 4),
            "max_session_loss_usdc": self.max_session_loss_usdc,
            "max_day_loss_usdc": self.max_day_loss_usdc,
            "rho": self.rho,
            "effective_independent_lines": round(self.effective_independent_lines, 3),
            "stagger_s": self.stagger_s,
        }


def effective_lines(n: int, rho: float = DEFAULT_SAME_MARKET_RHO) -> float:
    """Diversificación efectiva: 1 + (n-1)*(1-rho)."""
    n = max(1, int(n))
    rho = max(0.0, min(0.99, float(rho)))
    return 1.0 + (n - 1) * (1.0 - rho)


def build_risk_budget(
    *,
    lines: int = 2,
    capital_per_line: float = 1.5,
    rho: float = DEFAULT_SAME_MARKET_RHO,
    max_session_loss: float = 0.40,
    max_day_loss: float = 1.0,
    stagger_s: float = 45.0,
    desk_notional_cap: float | None = None,
) -> RiskBudget:
    n = max(1, int(lines))
    # Cap desk: no más de ~2.5× capital de una línea por correlación.
    eff = effective_lines(n, rho)
    raw_notional = float(capital_per_line) * n
    # Haircut: notional efectivo de riesgo ≈ capital * eff * 1.15 buffer
    risk_notional = float(capital_per_line) * eff * 1.15
    cap = float(desk_notional_cap) if desk_notional_cap is not None else max(
        float(capital_per_line) * 2.5, risk_notional
    )
    # Si el notional raw supera el cap, reducir líneas recomendadas implícitamente
    # (el presupuesto sigue reportando n pedido + warning via cap).
    return RiskBudget(
        max_lines=n,
        capital_per_line_usdc=float(capital_per_line),
        max_desk_notional_usdc=min(raw_notional, cap),
        max_session_loss_usdc=float(max_session_loss),
        max_day_loss_usdc=float(max_day_loss),
        rho=float(rho),
        effective_independent_lines=eff,
        stagger_s=float(stagger_s),
    )


def ev_per_filled_session(
    *,
    wr: float,
    avg_win: float,
    avg_loss: float,
) -> float:
    """EV esperado por sesión con fill decisivo (flats≈0)."""
    w = max(0.0, min(1.0, float(wr)))
    return w * float(avg_win) + (1.0 - w) * float(avg_loss)


def forecast_pnl(
    *,
    hours: float = 1.0,
    lines: int = 1,
    wr: float | None = None,
    avg_win: float | None = None,
    avg_loss: float | None = None,
    fill_rate: float | None = None,
    sessions_per_hour: float | None = None,
    rho: float = DEFAULT_SAME_MARKET_RHO,
    capital_scale: float = 1.0,
) -> dict[str, Any]:
    """Previsión de ganancia con haircut de correlación.

    capital_scale: 1.0 = paper@10 size; micro 1.5≈0.15 relativo a size 3@$10
    (conservador: size live floors a 5 shares → ~1.0–1.5× paper size en notional).
    """
    wr = float(DEFAULT_EV["wr"] if wr is None else wr)
    avg_win = float(DEFAULT_EV["avg_win_usdc"] if avg_win is None else avg_win)
    avg_loss = float(DEFAULT_EV["avg_loss_usdc"] if avg_loss is None else avg_loss)
    fill_rate = float(DEFAULT_EV["fill_rate"] if fill_rate is None else fill_rate)
    sph = float(
        DEFAULT_EV["sessions_per_hour"]
        if sessions_per_hour is None
        else sessions_per_hour
    )
    ev1 = ev_per_filled_session(wr=wr, avg_win=avg_win, avg_loss=avg_loss)
    # Escala de tamaño (micro vs paper)
    ev1_scaled = ev1 * float(capital_scale)
    fills_per_line_h = sph * fill_rate * float(hours)
    naive_lines = float(lines) * fills_per_line_h * ev1_scaled
    eff = effective_lines(int(lines), rho)
    corr_adj = eff * fills_per_line_h * ev1_scaled
    # Banda: p25 / base / p75 (simple, sin sobreprometer)
    return {
        "hours": float(hours),
        "lines": int(lines),
        "wr": round(wr, 4),
        "ev_per_fill_usdc": round(ev1_scaled, 4),
        "fill_rate": round(fill_rate, 4),
        "fills_per_line": round(fills_per_line_h, 3),
        "rho": rho,
        "effective_lines": round(eff, 3),
        "pnl_naive_n_times_usdc": round(naive_lines, 4),
        "pnl_corr_adjusted_usdc": round(corr_adj, 4),
        "band_p25_usdc": round(corr_adj * 0.45, 4),
        "band_base_usdc": round(corr_adj, 4),
        "band_p75_usdc": round(corr_adj * 1.35, 4),
        "warning": (
            "Paralelismo en mismo BTC 5m está correlacionado: "
            "usa pnl_corr_adjusted, no N×. Paper ≠ live (fees/latency/fills)."
        ),
        "capital_scale": float(capital_scale),
    }


def ladder_stage(current_capital: float) -> dict[str, Any]:
    ladder = list(CAPITAL_LADDER_USDC)
    cur = float(current_capital)
    nxt = None
    for x in ladder:
        if cur + 1e-9 < x:
            nxt = x
            break
    idx = 0
    for i, x in enumerate(ladder):
        if cur + 1e-9 >= x:
            idx = i
    return {
        "ladder_usdc": ladder,
        "current": cur,
        "stage_index": idx,
        "next_stage": nxt,
        "rule": "Subir peldaño solo tras ≥3 sesiones live limpia (sin dust/wrong-token) y WR≥70% en vivo.",
    }


def metrics_from_robust(m: dict[str, Any]) -> dict[str, float]:
    """Extrae wr / proxies de win-loss desde métricas robustas del gate."""
    wr = float(m.get("wr") or 0)
    decisive = int(m.get("decisive") or 0)
    total = float(m.get("total_robust") or 0)
    # Sin avg win/loss en gate → estimar simétrico a partir de EV≈total/decisive
    ev = (total / decisive) if decisive else 0.0
    # Asumir |avg_loss|≈|avg_win|≈a → EV = (2wr-1)*a → a = EV/(2wr-1)
    denom = 2.0 * wr - 1.0
    if abs(denom) > 0.05 and decisive >= 4:
        a = abs(ev / denom)
        avg_win = a
        avg_loss = -a
    else:
        avg_win = float(DEFAULT_EV["avg_win_usdc"])
        avg_loss = float(DEFAULT_EV["avg_loss_usdc"])
    return {
        "wr": wr,
        "avg_win_usdc": avg_win,
        "avg_loss_usdc": avg_loss,
        "ev_proxy": ev,
        "decisive": float(decisive),
    }


def collision_rate(market_ids_per_line: list[list[str]]) -> dict[str, Any]:
    """Tasa de colisión: misma market_id traded por ≥2 líneas."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for mids in market_ids_per_line:
        for mid in set(mids):
            counts[mid] += 1
    collided = sum(1 for c in counts.values() if c >= 2)
    total = len(counts) or 1
    return {
        "unique_markets": len(counts),
        "collided_markets": collided,
        "collision_rate": round(collided / total, 4),
        "note": "Alta colisión ⇒ correlación alta ⇒ no multiplicar PnL por N.",
    }
