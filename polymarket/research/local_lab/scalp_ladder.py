"""Metodología SCALP LADDER — ingresos incrementales controlados.

Reglas (por jugada / posición abierta):
1. En verde: pillar en el primer escalón alcanzado (1 / 2 / 3 / 4 USDC).
   Nunca hold más allá del techo (4 USDC).
2. También bank temprano en micro-verde (`early_bank`) para acumular poco a poco
   cuando el move no llega a +1€ (típico en 5 shares).
3. En rojo: cancelar de inmediato tras un micro-hold anti-ruido (`scalp_cut`).
4. Tras bank o cut: no pyramid; siguiente jugada en la misma sesión si queda cupo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


DEFAULT_LADDER: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0)


@dataclass(frozen=True)
class ScalpDecision:
    action: str  # "hold" | "bank" | "cut" | "cap"
    reason: str
    unreal: float
    rung: float | None = None


def parse_ladder(raw: Any) -> tuple[float, ...]:
    if not raw:
        return DEFAULT_LADDER
    if isinstance(raw, (int, float)):
        return (float(raw),)
    out: list[float] = []
    for x in raw:  # type: ignore[union-attr]
        try:
            v = float(x)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out.append(v)
    return tuple(sorted(set(out))) if out else DEFAULT_LADDER


def decide_scalp_exit(
    *,
    unreal: float,
    hold_s: float,
    ladder: Sequence[float] = DEFAULT_LADDER,
    early_bank_usdc: float = 0.05,
    scalp_cut_usdc: float = 0.08,
    min_hold_cut_s: float = 3.0,
    max_bank_usdc: float = 4.0,
) -> ScalpDecision:
    """Decisión pura de salida scalp (sin I/O)."""
    u = float(unreal)
    rungs = parse_ladder(ladder)
    cap = float(max_bank_usdc) if max_bank_usdc > 0 else (rungs[-1] if rungs else 4.0)

    # Techo duro: nunca hold por encima del máximo
    if u >= cap - 1e-12:
        return ScalpDecision("cap", "scalp_cap", u, cap)

    # Escalones 1/2/3/4: pillar el primero alcanzado
    for rung in rungs:
        if rung <= cap + 1e-12 and u >= rung - 1e-12:
            return ScalpDecision("bank", "scalp_ladder", u, float(rung))

    # Micro-verde: acumular poco a poco (5sh no siempre llega a +1€)
    if early_bank_usdc > 0 and u >= float(early_bank_usdc) - 1e-12:
        return ScalpDecision("bank", "scalp_early_bank", u, float(early_bank_usdc))

    # Rojo: cancelar ya (tras micro-hold anti-ruido de ticks)
    if scalp_cut_usdc > 0 and u <= -float(scalp_cut_usdc) + 1e-12:
        if hold_s + 1e-12 >= float(min_hold_cut_s):
            return ScalpDecision("cut", "scalp_cut", u, float(scalp_cut_usdc))
        return ScalpDecision("hold", "scalp_cut_hold_gate", u, float(scalp_cut_usdc))

    return ScalpDecision("hold", "scalp_hold", u, None)
