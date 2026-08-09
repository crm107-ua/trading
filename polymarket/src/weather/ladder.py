"""
Temperature ladder math — positive-skew cluster of adjacent buckets.

From: "Temperature ladder Polymarket bot" (Blockchain Surfer / @0xSurferX).
Own the neighborhood; one winner pays for the block.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class BucketQuote:
    name: str
    my_prob: float
    market_price: float  # ask / executable YES price in [0, 1]
    temp_c: int | None = None  # center temp for adjacent clustering; None = open-ended


@dataclass(frozen=True)
class LadderLeg:
    name: str
    my_prob: float
    price: float
    dollars: float
    shares: float
    ev: float


@dataclass(frozen=True)
class LadderPlan:
    legs: list[LadderLeg]
    basket_cost: float
    basket_ev: float
    center_temp: int
    underdispersed: bool
    take: bool
    reason: str


def calc_ev(p: float, price: float) -> float:
    """Edge per dollar on a single YES bucket."""
    if price <= 0 or price >= 1:
        return 0.0
    return round(p * (1.0 / price - 1.0) - (1.0 - p), 4)


def ladder_ev(buckets: Sequence[tuple[str, float, float]]) -> tuple[float, dict[str, float]]:
    """
    Weighted EV across the cluster.
    buckets: list of (name, my_prob, market_price)
    Returns (total_ev, per_bucket_ev).
    """
    total_ev = 0.0
    per: dict[str, float] = {}
    for name, p, price in buckets:
        ev = calc_ev(p, price)
        per[name] = ev
        total_ev += ev * price  # weight by dollars at risk on that rung
    return round(total_ev, 4), per


def size_ladder(
    buckets: Sequence[tuple[str, float, float]],
    budget: float,
) -> list[tuple[str, float, float]]:
    """
    Size each rung by model probability, scaled to a fixed budget.
    Returns list of (name, dollars, shares).
    """
    total_p = sum(max(0.0, p) for _, p, _ in buckets)
    if total_p <= 1e-12 or budget <= 0:
        return [(name, 0.0, 0.0) for name, _, _ in buckets]
    plan: list[tuple[str, float, float]] = []
    for name, p, price in buckets:
        weight = max(0.0, p) / total_p
        dollars = round(budget * weight, 2)
        if price <= 0:
            shares = 0.0
        else:
            shares = round(dollars / price, 2)
        plan.append((name, dollars, shares))
    return plan


def underdispersion_signal(
    model_temps: Sequence[float],
    typical_spread: float,
    *,
    tight_ratio: float = 0.65,
) -> dict[str, float | bool]:
    """
    When today's multi-model spread is tighter than usual, press the ladder.
    """
    if len(model_temps) < 2 or typical_spread <= 0:
        return {
            "spread": 0.0,
            "typical": float(typical_spread),
            "ratio": 1.0,
            "underdispersed": False,
        }
    spread = float(max(model_temps) - min(model_temps))
    ratio = spread / float(typical_spread)
    return {
        "spread": round(spread, 3),
        "typical": float(typical_spread),
        "ratio": round(ratio, 3),
        "underdispersed": bool(ratio <= tight_ratio),
    }


def select_adjacent_cluster(
    buckets: Sequence[BucketQuote],
    center_temp: int,
    *,
    width: int = 3,
) -> list[BucketQuote]:
    """
    Pick `width` adjacent point buckets centered on corrected forecast.
    Prefers exact °C buckets; open-ended tails only if needed to fill width.
    """
    width = max(2, min(4, int(width)))
    points = [b for b in buckets if b.temp_c is not None]
    if not points:
        return list(buckets)[:width]

    # Ideal window: center and neighbors
    half_left = (width - 1) // 2
    desired = list(range(center_temp - half_left, center_temp - half_left + width))
    by_temp = {int(b.temp_c): b for b in points if b.temp_c is not None}
    chosen = [by_temp[t] for t in desired if t in by_temp]

    if len(chosen) < width:
        # Expand outward from center until width filled
        ordered = sorted(points, key=lambda b: abs(int(b.temp_c) - center_temp))  # type: ignore[arg-type]
        seen = {b.name for b in chosen}
        for b in ordered:
            if b.name in seen:
                continue
            chosen.append(b)
            seen.add(b.name)
            if len(chosen) >= width:
                break
    # Keep ascending temperature order
    chosen.sort(key=lambda b: (b.temp_c is None, b.temp_c if b.temp_c is not None else 10**9))
    return chosen[:width]


def build_ladder_plan(
    buckets: Sequence[BucketQuote],
    *,
    center_temp: int,
    model_temps: Sequence[float],
    typical_spread: float,
    budget: float,
    max_basket_cost: float = 0.50,
    min_cluster_prob: float = 0.55,
    min_basket_ev: float = 0.02,
    width: int = 3,
    press_on_underdispersion: bool = True,
    max_leg_price: float = 0.42,
) -> LadderPlan:
    """
    Full decision: cluster → EV → underdispersion → size → take/skip.
    Basket cost here is sum of YES prices (unit shares); dollar budget is separate.
    """
    cluster = select_adjacent_cluster(buckets, center_temp, width=width)
    if len(cluster) < 2:
        return LadderPlan([], 0.0, 0.0, center_temp, False, False, "cluster_too_small")

    unit_cost = sum(b.market_price for b in cluster)
    cluster_prob = sum(b.my_prob for b in cluster)
    max_leg = max(b.market_price for b in cluster)
    tuples = [(b.name, b.my_prob, b.market_price) for b in cluster]
    total_ev, per_ev = ladder_ev(tuples)
    ud = underdispersion_signal(model_temps, typical_spread)
    under = bool(ud["underdispersed"])
    point_temps = [int(b.temp_c) for b in buckets if b.temp_c is not None]

    reason_parts: list[str] = []
    take = True
    # Open-ended floor trap: center below all °C buckets → ladder sits on 28/29/30
    # while resolution can pay "27°C or below" (Beijing 2026-07-10 style).
    if point_temps and int(center_temp) < min(point_temps):
        take = False
        reason_parts.append("center_below_ladder_floor")
    if unit_cost <= 0 or unit_cost > max_basket_cost:
        take = False
        reason_parts.append(f"basket_cost={unit_cost:.3f}>max={max_basket_cost}")
    # Article Singapore shape peaked ~39c — a 48c+ leg means skew is already gone.
    if max_leg_price > 0 and max_leg > max_leg_price:
        take = False
        reason_parts.append(f"max_leg={max_leg:.3f}>{max_leg_price}")
    if cluster_prob < min_cluster_prob:
        take = False
        reason_parts.append(f"cluster_p={cluster_prob:.3f}<{min_cluster_prob}")
    if total_ev < min_basket_ev:
        take = False
        reason_parts.append(f"ev={total_ev:.4f}<{min_basket_ev}")
    # Article upgrade: press when ensemble is tight; skip wide disagreement by default.
    if press_on_underdispersion and not under:
        take = False
        reason_parts.append("not_underdispersed")

    # Size: underdispersion → press; also scale budget up when EV is fat & basket cheap.
    press = 1.0
    if take and under:
        press *= 1.35
    if take and total_ev >= 0.08 and unit_cost <= 0.45:
        press *= 1.15
    eff_budget = budget * press
    # Center-heavier when underdispersed: square probability weights
    if under and take:
        total_p = sum(max(0.0, p) for _, p, _ in tuples) or 1.0
        squared = [(n, (max(0.0, p) ** 2), px) for n, p, px in tuples]
        z = sum(p for _, p, _ in squared) or 1.0
        tuples_sized = [(n, p / z, px) for n, p, px in squared]
        sized = size_ladder(tuples_sized, eff_budget)
    else:
        sized = size_ladder(tuples, eff_budget)
    legs = [
        LadderLeg(
            name=name,
            my_prob=p,
            price=price,
            dollars=dollars,
            shares=shares,
            ev=per_ev.get(name, 0.0),
        )
        for (name, p, price), (name2, dollars, shares) in zip(tuples, sized, strict=True)
    ]
    if take:
        reason_parts.append("take")
        if under:
            reason_parts.append("underdispersed_press")
    return LadderPlan(
        legs=legs,
        basket_cost=round(unit_cost, 4),
        basket_ev=total_ev,
        center_temp=center_temp,
        underdispersed=under,
        take=take,
        reason="+".join(reason_parts) if reason_parts else "skip",
    )


def truncate_temp(value_c: float) -> int:
    """Polymarket weather resolves by truncation, not rounding."""
    return math.floor(float(value_c) + 1e-9)


def gaussian_bucket_probs(
    center: float,
    sigma: float,
    temps: Iterable[int],
) -> dict[int, float]:
    """Softmax-ish discrete masses from Normal(center, sigma) at integer temps."""
    sig = max(0.35, float(sigma))
    scores: dict[int, float] = {}
    for t in temps:
        z = (float(t) + 0.5 - float(center)) / sig  # bin center at t+0.5 for truncation world
        # density at bin midpoint
        scores[t] = math.exp(-0.5 * z * z)
    zsum = sum(scores.values()) or 1.0
    return {t: v / zsum for t, v in scores.items()}
