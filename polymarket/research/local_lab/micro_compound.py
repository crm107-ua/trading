"""Lógica de micro-compound 1–2€: reinversión segura iterativa.

Diseño pionero (más seguro que scale/paralelo):
- 1 sola línea (sin colisión ρ≈0.85)
- Capital sesión = min(bankroll, hard_cap)
- Solo postea si 5 shares × px ≤ capital (floor CLOB)
- Tras win: acumula; tras loss: cooldown / reduce size
- Kill diario y por racha
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MIN_SHARES = 5.0
DEFAULT_START_USDC = 2.0
HARD_CAP_USDC = 5.0  # no escalar ciego por encima de micro
MAX_SESSION_FRAC = 1.0  # usa todo el bankroll micro (ya es pequeño)
LOSS_COOLDOWN_ROUNDS = 1
MAX_CONSEC_LOSSES = 3  # permitir 1 loss + 1 starve recovery antes de kill


@dataclass
class MicroState:
    bankroll: float = DEFAULT_START_USDC
    peak: float = DEFAULT_START_USDC
    start_bankroll: float = DEFAULT_START_USDC
    rounds: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    consec_losses: int = 0
    cooldown_left: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    halted: bool = False
    halt_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bankroll": round(self.bankroll, 4),
            "peak": round(self.peak, 4),
            "start_bankroll": round(self.start_bankroll, 4),
            "rounds": self.rounds,
            "wins": self.wins,
            "losses": self.losses,
            "flats": self.flats,
            "wr": round(
                self.wins / (self.wins + self.losses), 4
            )
            if (self.wins + self.losses)
            else 0.0,
            "consec_losses": self.consec_losses,
            "cooldown_left": self.cooldown_left,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "pnl_total": round(self.bankroll - self.start_bankroll, 4),
            "history": self.history,
        }


def max_affordable_price(capital: float, shares: float = MIN_SHARES) -> float:
    """Precio máximo para que 5 shares quepan en el capital."""
    if capital <= 0 or shares <= 0:
        return 0.0
    return max(0.01, min(0.99, float(capital) / float(shares) - 0.001))


def session_capital(state: MicroState, *, hard_cap: float = HARD_CAP_USDC) -> float:
    if state.halted or state.cooldown_left > 0:
        return 0.0
    return max(0.0, min(float(state.bankroll) * MAX_SESSION_FRAC, float(hard_cap)))


def can_afford_entry(capital: float, price: float, shares: float = MIN_SHARES) -> bool:
    return float(price) * float(shares) <= float(capital) + 1e-9


def apply_round_result(
    state: MicroState,
    *,
    net: float,
    fills: int,
    start_capital: float | None = None,
) -> MicroState:
    """Actualiza bankroll tras una sesión sim/live."""
    if state.halted:
        return state
    if state.cooldown_left > 0:
        state.cooldown_left -= 1
        state.history.append(
            {
                "round": state.rounds + 1,
                "skipped": True,
                "reason": "cooldown",
                "bankroll": state.bankroll,
            }
        )
        state.rounds += 1
        return state

    state.rounds += 1
    net = float(net)
    fills = int(fills)
    state.bankroll = round(float(state.bankroll) + net, 6)
    state.peak = max(state.peak, state.bankroll)

    if fills <= 0 or abs(net) <= 1e-9:
        state.flats += 1 if fills > 0 else 0
        tag = "flat" if fills > 0 else "starve"
        state.consec_losses = 0 if tag == "flat" else state.consec_losses
    elif net > 0:
        state.wins += 1
        state.consec_losses = 0
        tag = "win"
    else:
        state.losses += 1
        state.consec_losses += 1
        tag = "loss"
        state.cooldown_left = LOSS_COOLDOWN_ROUNDS

    state.history.append(
        {
            "round": state.rounds,
            "tag": tag,
            "net": round(net, 4),
            "fills": fills,
            "start_capital": start_capital,
            "bankroll": round(state.bankroll, 4),
        }
    )

    # Kill: bankroll bajo mínimo operable (~1.0 no llega a 5sh×0.25)
    if state.bankroll + 1e-9 < 1.25:
        state.halted = True
        state.halt_reason = "bankroll_below_min_operable"
    elif state.consec_losses >= MAX_CONSEC_LOSSES:
        state.halted = True
        state.halt_reason = "max_consec_losses"
    elif state.bankroll <= state.peak - 1.0 and state.peak >= 2.0:
        # Drawdown 1€ desde pico en micro → stop
        state.halted = True
        state.halt_reason = "drawdown_1eur_from_peak"

    return state


def recommend_path(comparison: dict[str, Any]) -> dict[str, Any]:
    """Elige el camino más seguro/pionero según métricas."""
    ranked = sorted(
        comparison.get("paths") or [],
        key=lambda p: (
            int(bool(float(p.get("wr") or 0) >= 0.80)),
            int(bool(p.get("safer"))),
            float(p.get("pnl") or 0),
            -float(p.get("collision_risk") or 0),
        ),
        reverse=True,
    )
    best = ranked[0] if ranked else None
    return {
        "recommended": best.get("id") if best else None,
        "reason": (
            "1 línea micro-compound: sin colisión, reinversión, kill por racha/DD. "
            "Más seguro que scale/paralelo; PnL por trade menor pero acumulable."
            if best and best.get("id") == "micro2_single"
            else "Ver paths"
        ),
        "ranked": [p.get("id") for p in ranked],
    }
