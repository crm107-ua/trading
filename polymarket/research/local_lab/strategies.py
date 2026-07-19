"""Paper-maker strategies for local lab (non-binding)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QuoteIntent:
    bid: float
    ask: float
    size_shares: float
    strategy_id: str
    note: str = ""


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def maker_16(
    fair_up: float,
    cfg: dict[str, Any],
    best_bid: float | None = None,
    best_ask: float | None = None,
) -> QuoteIntent:
    """Frozen #16 — PREREG_16 params; optional join-touch for paper liquidity."""
    hs = float(cfg["half_spread"])
    buf = float(cfg["safety_buffer"])
    size = float(cfg["quote_size_shares"])
    bid = _clip(fair_up - hs - buf, 0.01, 0.98)
    ask = _clip(fair_up + hs + buf, 0.02, 0.99)
    if cfg.get("quote_join_touch") and best_bid is not None and best_ask is not None:
        # Join touch only when still on the safe side of fair
        if best_bid <= fair_up - buf:
            bid = _clip(best_bid, 0.01, 0.98)
        if best_ask >= fair_up + buf:
            ask = _clip(best_ask, 0.02, 0.99)
        if ask <= bid:
            ask = _clip(bid + 0.02, 0.02, 0.99)
    return QuoteIntent(bid, ask, size, "maker_16", "pre-reg frozen")


def apply_inventory_skew(
    quote: QuoteIntent,
    *,
    inventory_shares: float,
    cfg: dict[str, Any],
    mid: float | None = None,
) -> QuoteIntent | None:
    """
    Inventory control:
    - any long → only ask (reduce); any short → only bid
    - at/over cap → still quote reducing side (never mute exits)
    """
    size = float(cfg["quote_size_shares"])
    max_inv_shares = float(cfg.get("max_inventory_shares", size * 2))
    skew_shares = float(cfg.get("inventory_skew_shares", size))
    bid, ask = quote.bid, quote.ask
    note = quote.note
    tick = 0.01
    exit_size = min(size, abs(inventory_shares)) if abs(inventory_shares) > 1e-9 else size

    if inventory_shares > 1e-9:
        # Reduce long — join ask touch / mid+tick
        bid = 0.01
        if mid is not None:
            ask = _clip(mid + tick, 0.02, 0.99)
        elif ask >= 0.98:
            return None
        note = f"{note}|exit_long".strip("|")
        return QuoteIntent(bid, ask, exit_size, quote.strategy_id, note)
    if inventory_shares < -1e-9:
        ask = 0.99
        if mid is not None:
            bid = _clip(mid - tick, 0.01, 0.98)
        elif bid <= 0.02:
            return None
        note = f"{note}|exit_short".strip("|")
        return QuoteIntent(bid, ask, exit_size, quote.strategy_id, note)

    # Flat book: refuse to open if quote would breach caps later; keep entry quote
    if abs(inventory_shares) >= max_inv_shares - 1e-9:
        return None
    if ask - bid < 0.01:
        return None
    # Optional soft skew unused when flat
    _ = skew_shares
    return QuoteIntent(bid, ask, quote.size_shares, quote.strategy_id, note)


def wide_spread_only(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    spot: float,
    strike: float,
    cfg: dict[str, Any],
) -> QuoteIntent | None:
    """Probe #17-local: quote solo si el libro retail está muy ancho."""
    min_spread = float(cfg.get("min_market_spread", 0.04))
    if best_bid is None or best_ask is None:
        return None
    if best_ask - best_bid < min_spread:
        return None
    q = maker_16(fair_up, cfg)
    return QuoteIntent(q.bid, q.ask, q.size_shares, "wide_spread_probe", f"market_spread>={min_spread}")


def tight_mid_fade(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    spot: float,
    strike: float,
    cfg: dict[str, Any],
) -> QuoteIntent | None:
    """Probe #18-local: solo ask cuando spot>strike y mid está barato vs fair."""
    if best_bid is None or best_ask is None:
        return None
    mid = (best_bid + best_ask) / 2
    if spot <= strike or fair_up - mid < 0.03:
        return None
    size = float(cfg["quote_size_shares"])
    ask = _clip(fair_up + float(cfg["half_spread"]), 0.02, 0.99)
    bid = _clip(fair_up - float(cfg["half_spread"]) - 0.02, 0.01, 0.98)
    return QuoteIntent(bid, ask, size, "tight_mid_fade", "spot>strike & mid stale")


def maker_edge(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    spot: float,
    strike: float,
    cfg: dict[str, Any],
) -> QuoteIntent | None:
    """
    Selective maker: quote only when |fair - mid| >= min_edge.
    Cheap market → bid at touch; rich market → ask at touch.
    High-margin mode: tiered size + min expected pnl filter.
    """
    if best_bid is None or best_ask is None:
        return None
    mid = (best_bid + best_ask) / 2.0
    min_edge = float(cfg.get("min_edge", 0.03))
    sigma = float(cfg.get("sigma_mid", 0.03))
    edge = fair_up - mid
    abs_edge = abs(edge)
    z = abs_edge / max(sigma, 1e-6)
    min_z = float(cfg.get("min_z", 1.0))
    if abs_edge < min_edge or z < min_z:
        return None
    # Si |fair-mid| es enorme, el modelo suele estar mal (mid 0.95 vs fair 0.5).
    # No fades de mercados casi resueltos: matan el WR del grind.
    max_abs_edge = float(cfg.get("max_abs_edge", 0) or 0)
    if max_abs_edge > 0 and abs_edge > max_abs_edge:
        return None

    # Evita lotería (YES a 0.09 / 0.90): ahí el "edge" vs fair suele ser ruido de cola.
    mid_lo = float(cfg.get("min_quote_mid", 0.0) or 0.0)
    mid_hi = float(cfg.get("max_quote_mid", 1.0) or 1.0)
    if mid_lo > 0 and mid < mid_lo:
        return None
    if mid_hi < 1 and mid > mid_hi:
        return None

    # Optional time window (seconds remaining) — avoid open chaos / last-second junk.
    t_rem = cfg.get("_time_remaining_s")
    t_min = float(cfg.get("quote_time_min_s", 0) or 0)
    t_max = float(cfg.get("quote_time_max_s", 0) or 0)
    if t_rem is not None:
        if t_min > 0 and float(t_rem) < t_min:
            return None
        if t_max > 0 and float(t_rem) > t_max:
            return None

    hs = float(cfg["half_spread"])
    buf = float(cfg["safety_buffer"])
    base_size = float(cfg["quote_size_shares"])
    max_mult = float(cfg.get("max_size_mult", 2.5))
    # Tiered sizing: mediocre edge → small; premium edge → full throttle.
    soft = float(cfg.get("soft_edge", min_edge * 1.4))
    hard = float(cfg.get("hard_edge", min_edge * 2.2))
    if cfg.get("kelly_sizing", True):
        if abs_edge >= hard:
            f = max_mult
        elif abs_edge >= soft:
            f = 1.0 + (max_mult - 1.0) * (abs_edge - soft) / max(hard - soft, 1e-6)
        else:
            f = float(cfg.get("soft_size_frac", 0.55))
        size = max(1.0, round(base_size * f, 2))
    else:
        size = base_size
    size = max(1.0, round(size * float(cfg.get("_runtime_size_scale", 1.0) or 1.0), 2))
    # Hard cap — evita size 42×3.0=126 que tumba la sesión de 100€
    hard_cap = float(cfg.get("max_quote_size_shares", 0) or 0)
    if hard_cap > 0:
        size = min(size, hard_cap)

    # Skip unless expected capture (edge * size * capture_frac) clears hurdle on $100 book.
    capture = float(cfg.get("expected_capture_frac", 0.45))
    min_ev = float(cfg.get("min_expected_pnl_usdc", 0.0) or 0.0)
    if min_ev > 0 and abs_edge * size * capture < min_ev:
        return None

    mkt_spread = best_ask - best_bid
    if mkt_spread < float(cfg.get("min_market_spread", 0.0)):
        return None

    # Solo lado cheap (bid) si rich está desactivado (grind / micro_strict).
    allow_rich = bool(
        cfg.get(
            "allow_rich_side",
            cfg.get("allow_rich_side_live", True),
        )
    )
    if cfg.get("cheap_side_only", False):
        allow_rich = False

    # Opcional: no fadraar sin confirmación de momentum (Fusion/WR-lock).
    if bool(cfg.get("require_momentum_align", False)):
        roll = float(cfg.get("_roll_lead_usd", 0.0) or 0.0)
        min_roll = float(cfg.get("min_spot_lead_usd", 2.0) or 2.0)
        if edge >= min_edge and roll < min_roll:
            return None  # cheap UP sin BTC subiendo → tóxico
        if edge <= -min_edge and roll > -min_roll:
            return None  # rich UP sin BTC bajando → tóxico

    if edge >= min_edge:
        bid = _clip(best_bid if cfg.get("quote_join_touch", True) else fair_up - hs - buf, 0.01, 0.98)
        if bid >= mid - 1e-9:
            return None
        # No bids en colas extremas aunque el mid pase el filtro por un tick.
        if mid_lo > 0 and bid < mid_lo:
            return None
        ask = 0.99
        return QuoteIntent(bid, ask, size, "maker_edge", f"cheap e={abs_edge:.3f} sz={size}")
    if not allow_rich:
        return None
    ask = _clip(best_ask if cfg.get("quote_join_touch", True) else fair_up + hs + buf, 0.02, 0.99)
    if ask <= mid + 1e-9:
        return None
    if mid_hi < 1 and ask > mid_hi:
        return None
    bid = 0.01
    return QuoteIntent(bid, ask, size, "maker_edge", f"rich e={abs_edge:.3f} sz={size}")


def pulse_spot_fair(spot: float, strike: float, scale_usd: float) -> float:
    """Latencia-fair: P(up) vía sigmoide de (spot−strike). Más reactivo que BS en 5m."""
    scale = max(float(scale_usd), 1e-6)
    x = (float(spot) - float(strike)) / scale
    # clip exp for stability
    x = max(-20.0, min(20.0, x))
    p = 1.0 / (1.0 + math.exp(-x))
    return max(0.05, min(0.95, p))


def maker_pulse(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    spot: float,
    strike: float,
    cfg: dict[str, Any],
) -> QuoteIntent | None:
    """
    PulseGate — régimen + latencia BTC→libro + anti-toxicidad.

    No fadra mids informados. Cotiza cuando el spot confirma y el mid rezaga:
      UP (bid):  spot>strike + vel+ + fair>mid
      DOWN (ask, simétrico): spot<strike + vel− + fair<mid
    Gates comunes: strike fresco, blackout settlement, régimen mid, persistencia, imbalance.
    Edge primario: pulse_spot_fair (sigmoide), opcionalmente max con BS fair_up.
    """
    if best_bid is None or best_ask is None:
        return None
    if not bool(cfg.get("_strike_trusted", True)):
        return None

    mid = (best_bid + best_ask) / 2.0
    mid_lo = float(cfg.get("min_quote_mid", 0.38) or 0.38)
    mid_hi = float(cfg.get("max_quote_mid", 0.62) or 0.62)
    if mid < mid_lo or mid > mid_hi:
        return None

    # Blackout de settlement (literatura 2026: push en últimos ~10–60s).
    t_rem = cfg.get("_time_remaining_s")
    t_min = float(cfg.get("quote_time_min_s", 110) or 110)
    t_max = float(cfg.get("quote_time_max_s", 260) or 260)
    if t_rem is not None:
        if float(t_rem) < t_min or float(t_rem) > t_max:
            return None

    # Lead rodante (spot vs hace ~8s). El lead vs open se anula al sellar strike.
    vel = float(cfg.get("_spot_velocity_usd", 0.0) or 0.0)
    roll = float(cfg.get("_roll_lead_usd", float(spot) - float(strike)) or 0.0)
    min_lead = float(cfg.get("min_spot_lead_usd", 12.0) or 12.0)
    min_vel = float(cfg.get("min_spot_velocity_usd", 4.0) or 4.0)

    scale = float(cfg.get("pulse_fair_scale_usd", 28.0) or 28.0)
    spot_fair = pulse_spot_fair(float(spot), float(spot) - roll, scale)
    # Mezcla: spot-fair (latencia) + BS; más extremo en la dirección del roll.
    if bool(cfg.get("pulse_blend_bs_fair", True)):
        if roll >= 0:
            model_fair = max(float(fair_up), spot_fair)
        else:
            model_fair = min(float(fair_up), spot_fair)
    else:
        model_fair = spot_fair

    edge = model_fair - mid  # >0 cheap UP; <0 rich UP
    min_edge = float(cfg.get("min_edge", 0.028) or 0.028)
    max_abs_edge = float(cfg.get("max_abs_edge", 0.09) or 0.09)
    abs_edge = abs(edge)
    if abs_edge < min_edge or abs_edge > max_abs_edge:
        return None
    sigma = float(cfg.get("sigma_mid", 0.03) or 0.03)
    if abs_edge / max(sigma, 1e-6) < float(cfg.get("min_z", 0.9) or 0.9):
        return None

    symmetric = bool(cfg.get("pulse_symmetric", True))
    side: str | None = None
    if roll >= min_lead and vel >= min_vel and edge >= min_edge:
        side = "bid"  # latency long UP
    elif (
        symmetric
        and roll <= -min_lead
        and vel <= -min_vel
        and edge <= -min_edge
    ):
        side = "ask"  # latency short UP / confirm DOWN
    if side is None:
        return None

    # Mid-lag: el libro no ha absorbido el move del spot (núcleo latencia).
    mid_d = cfg.get("_mid_delta")
    max_mid_catch = float(cfg.get("max_mid_catchup", 0.025) or 0.025)
    if mid_d is not None:
        if side == "bid" and float(mid_d) > max_mid_catch:
            return None  # mid ya subió → sin lag
        if side == "ask" and float(mid_d) < -max_mid_catch:
            return None  # mid ya bajó → sin lag

    imb = cfg.get("_book_imbalance")
    min_imb = float(cfg.get("min_bid_imbalance", 0.52) or 0.52)
    if imb is not None:
        if side == "bid" and float(imb) < min_imb:
            return None  # ask-heavy contra bid
        if side == "ask" and float(imb) > (1.0 - min_imb):
            return None  # bid-heavy contra ask

    need = int(cfg.get("pulse_persist_polls", 2) or 2)
    if int(cfg.get("_pulse_streak", 0) or 0) < need:
        return None

    mkt_spread = best_ask - best_bid
    if mkt_spread < float(cfg.get("min_market_spread", 0.01) or 0.01):
        return None

    size = float(cfg["quote_size_shares"])
    size = max(1.0, round(size * float(cfg.get("_runtime_size_scale", 1.0) or 1.0), 2))
    hard_cap = float(cfg.get("max_quote_size_shares", 0) or 0)
    if hard_cap > 0:
        size = min(size, hard_cap)

    capture = float(cfg.get("expected_capture_frac", 0.5) or 0.5)
    min_ev = float(cfg.get("min_expected_pnl_usdc", 0.0) or 0.0)
    if min_ev > 0 and abs_edge * size * capture < min_ev:
        return None

    hs = float(cfg["half_spread"])
    if side == "bid":
        bid = _clip(
            best_bid if cfg.get("quote_join_touch", True) else model_fair - hs,
            0.01,
            0.98,
        )
        if bid >= mid - 1e-9 or (mid_lo > 0 and bid < mid_lo):
            return None
        return QuoteIntent(
            bid,
            0.99,
            size,
            "maker_pulse",
            f"pulse_up e={abs_edge:.3f} sf={spot_fair:.2f} roll={roll:.0f} vel={vel:.0f}",
        )

    ask = _clip(
        best_ask if cfg.get("quote_join_touch", True) else model_fair + hs,
        0.02,
        0.99,
    )
    if ask <= mid + 1e-9 or (mid_hi < 1 and ask > mid_hi):
        return None
    return QuoteIntent(
        0.01,
        ask,
        size,
        "maker_pulse",
        f"pulse_dn e={abs_edge:.3f} sf={spot_fair:.2f} roll={roll:.0f} vel={vel:.0f}",
    )


def maker_follow(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    spot: float,
    strike: float,
    cfg: dict[str, Any],
) -> QuoteIntent | None:
    """
    FollowGate — opuesto al fade: unirse al lado que el mid YA precio
    solo si el spot lo confirma (anti adverse-selection).

    UP:  mid en [follow_up_lo, follow_up_hi] y roll/vel ≥ 0
    DOWN: mid en banda baja y roll/vel ≤ 0
    Evita colas (>follow_extreme) y settlement.
    """
    if best_bid is None or best_ask is None:
        return None
    # Ventana debe estar abierta (no pre-book de nxt).
    if cfg.get("_window_open") is False:
        return None

    mid = (best_bid + best_ask) / 2.0
    extreme_hi = float(cfg.get("follow_extreme_hi", 0.78) or 0.78)
    extreme_lo = float(cfg.get("follow_extreme_lo", 0.22) or 0.22)
    if mid >= extreme_hi or mid <= extreme_lo:
        return None

    t_rem = cfg.get("_time_remaining_s")
    t_min = float(cfg.get("follow_time_min_s", cfg.get("quote_time_min_s", 80)) or 80)
    t_max = float(cfg.get("follow_time_max_s", cfg.get("quote_time_max_s", 280)) or 280)
    if t_rem is not None and (float(t_rem) < t_min or float(t_rem) > t_max):
        return None

    roll = float(cfg.get("_roll_lead_usd", 0.0) or 0.0)
    vel = float(cfg.get("_spot_velocity_usd", 0.0) or 0.0)
    min_roll = float(cfg.get("follow_min_roll_usd", 1.5) or 1.5)
    min_vel = float(cfg.get("follow_min_vel_usd", 0.3) or 0.3)

    up_lo = float(cfg.get("follow_up_lo", 0.52) or 0.52)
    up_hi = float(cfg.get("follow_up_hi", 0.72) or 0.72)
    dn_lo = float(cfg.get("follow_dn_lo", 0.28) or 0.28)
    dn_hi = float(cfg.get("follow_dn_hi", 0.48) or 0.48)

    side: str | None = None
    if up_lo <= mid <= up_hi and roll >= min_roll and vel >= min_vel:
        side = "bid"  # follow UP
    elif dn_lo <= mid <= dn_hi and roll <= -min_roll and vel <= -min_vel:
        side = "ask"  # follow DOWN
    if side is None:
        return None

    # BS-fair va detrás del mid en BTC 5m y vetaba entradas buenas.
    # Opt-in: follow_use_fair_veto=true + follow_fair_oppose_max.
    if bool(cfg.get("follow_use_fair_veto", False)):
        oppose = float(
            cfg.get("follow_fair_oppose_max", cfg.get("follow_min_fair_edge", 0.08))
            or 0.08
        )
        if side == "bid" and float(fair_up) < mid - oppose:
            return None
        if side == "ask" and float(fair_up) > mid + oppose:
            return None

    need = int(cfg.get("follow_persist_polls", 1) or 1)
    streak = int(cfg.get("_pulse_streak", 0) or 0)
    # Follow usa su propio agree vía roll+mid; acepta streak≥need o need≤1
    if need > 1 and streak < need:
        return None

    size = float(cfg["quote_size_shares"])
    size = max(1.0, round(size * float(cfg.get("_runtime_size_scale", 1.0) or 1.0), 2))
    hard_cap = float(cfg.get("max_quote_size_shares", 0) or 0)
    if hard_cap > 0:
        size = min(size, hard_cap)

    if side == "bid":
        bid = _clip(
            best_bid if cfg.get("quote_join_touch", True) else mid - 0.01,
            0.01,
            0.98,
        )
        if bid >= mid - 1e-9:
            return None
        return QuoteIntent(
            bid, 0.99, size, "maker_follow", f"follow_up mid={mid:.2f} roll={roll:.1f}"
        )
    ask = _clip(
        best_ask if cfg.get("quote_join_touch", True) else mid + 0.01,
        0.02,
        0.99,
    )
    if ask <= mid + 1e-9:
        return None
    return QuoteIntent(
        0.01, ask, size, "maker_follow", f"follow_dn mid={mid:.2f} roll={roll:.1f}"
    )


def maker_shadow_ofir(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    spot: float,
    strike: float,
    cfg: dict[str, Any],
) -> QuoteIntent | None:
    """
    Shadow OFIR — síntesis del edge que usan desks privados 2026 (no un leak):

    1) Latency lead: spot se mueve ANTES que el mid de Polymarket.
    2) Toxicity veto: imbalance de libro debe ALINEARSE (no cotizar contra flujo).
    3) Signal guard: mid aún no catchupeó (`max_mid_catchup` estricto).
    4) Avoid coin-flip: cerca de 0.50 exige lead/vel mayores.
    5) Settlement blackout: no entrar en la cola MEV final.

    No es “el secreto de un bot X”; es el stack privado típico (lead+toxicity+guard)
    empaquetado como DNA operable en nuestro runtime.
    """
    if best_bid is None or best_ask is None:
        return None
    if not bool(cfg.get("_strike_trusted", True)):
        return None
    if cfg.get("_window_open") is False:
        return None

    mid = (best_bid + best_ask) / 2.0
    mid_lo = float(cfg.get("shadow_min_quote_mid", cfg.get("min_quote_mid", 0.36)) or 0.36)
    mid_hi = float(cfg.get("shadow_max_quote_mid", cfg.get("max_quote_mid", 0.64)) or 0.64)
    if mid < mid_lo or mid > mid_hi:
        return None

    t_rem = cfg.get("_time_remaining_s")
    t_min = float(cfg.get("shadow_time_min_s", cfg.get("quote_time_min_s", 90)) or 90)
    t_max = float(cfg.get("shadow_time_max_s", cfg.get("quote_time_max_s", 270)) or 270)
    if t_rem is not None and (float(t_rem) < t_min or float(t_rem) > t_max):
        return None

    roll = float(cfg.get("_roll_lead_usd", 0.0) or 0.0)
    vel = float(cfg.get("_spot_velocity_usd", 0.0) or 0.0)
    min_lead = float(cfg.get("shadow_min_lead_usd", cfg.get("min_spot_lead_usd", 2.5)) or 2.5)
    min_vel = float(
        cfg.get("shadow_min_vel_usd", cfg.get("min_spot_velocity_usd", 0.7)) or 0.7
    )
    # Coin-flip zone: exigir más lead (evita adverse selection cerca de 50¢).
    coin_lo = float(cfg.get("shadow_coinflip_lo", 0.47) or 0.47)
    coin_hi = float(cfg.get("shadow_coinflip_hi", 0.53) or 0.53)
    if coin_lo <= mid <= coin_hi:
        min_lead *= float(cfg.get("shadow_coinflip_lead_mult", 1.6) or 1.6)
        min_vel *= float(cfg.get("shadow_coinflip_vel_mult", 1.4) or 1.4)

    scale = float(cfg.get("pulse_fair_scale_usd", 28.0) or 28.0)
    spot_fair = pulse_spot_fair(float(spot), float(spot) - roll, scale)
    if bool(cfg.get("pulse_blend_bs_fair", True)):
        model_fair = max(float(fair_up), spot_fair) if roll >= 0 else min(float(fair_up), spot_fair)
    else:
        model_fair = spot_fair
    edge = model_fair - mid
    min_edge = float(cfg.get("shadow_min_edge", cfg.get("min_edge", 0.018)) or 0.018)
    max_abs = float(cfg.get("max_abs_edge", 0.14) or 0.14)
    if abs(edge) < min_edge or abs(edge) > max_abs:
        return None

    side: str | None = None
    if roll >= min_lead and vel >= min_vel and edge >= min_edge:
        side = "bid"
    elif roll <= -min_lead and vel <= -min_vel and edge <= -min_edge:
        side = "ask"
    if side is None:
        return None

    # Núcleo privado: solo si el mid AÚN no reflejó el move (lag residual).
    mid_d = cfg.get("_mid_delta")
    max_mid_catch = float(cfg.get("shadow_max_mid_catchup", 0.018) or 0.018)
    if mid_d is None:
        return None  # sin serie de mid → no hay evidencia de lag
    if side == "bid" and float(mid_d) > max_mid_catch:
        return None
    if side == "ask" and float(mid_d) < -max_mid_catch:
        return None

    # Toxicity / OFIR: imbalance debe confirmar la dirección (VPIN-lite).
    imb = cfg.get("_book_imbalance")
    if imb is None:
        return None
    min_imb = float(cfg.get("shadow_min_imbalance", 0.55) or 0.55)
    max_opp = 1.0 - min_imb
    if side == "bid" and float(imb) < min_imb:
        return None  # asks dominan → toxic para comprar UP
    if side == "ask" and float(imb) > max_opp:
        return None  # bids dominan → toxic para vender UP

    need = int(cfg.get("shadow_persist_polls", 2) or 2)
    streak = int(cfg.get("_pulse_streak", 0) or 0)
    if streak < need:
        return None

    size = float(cfg["quote_size_shares"])
    size = max(1.0, round(size * float(cfg.get("_runtime_size_scale", 1.0) or 1.0), 2))
    hard_cap = float(cfg.get("max_quote_size_shares", 0) or 0)
    if hard_cap > 0:
        size = min(size, hard_cap)

    if side == "bid":
        bid = _clip(
            best_bid if cfg.get("quote_join_touch", True) else mid - 0.01,
            0.01,
            0.98,
        )
        if bid >= mid - 1e-9:
            return None
        return QuoteIntent(
            bid,
            0.99,
            size,
            "maker_shadow_ofir",
            f"shadow_up e={edge:.3f} roll={roll:.1f} imb={float(imb):.2f} md={float(mid_d):.3f}",
        )
    ask = _clip(
        best_ask if cfg.get("quote_join_touch", True) else mid + 0.01,
        0.02,
        0.99,
    )
    if ask <= mid + 1e-9:
        return None
    return QuoteIntent(
        0.01,
        ask,
        size,
        "maker_shadow_ofir",
        f"shadow_dn e={edge:.3f} roll={roll:.1f} imb={float(imb):.2f} md={float(mid_d):.3f}",
    )


def maker_fusion(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    spot: float,
    strike: float,
    cfg: dict[str, Any],
) -> QuoteIntent | None:
    """
    RegimeRouter: Shadow OFIR → Pulse → Follow → Edge selectivo.
    Shadow off por defecto (no altera DNAs pulse/flow existentes).
    """
    # 0) Shadow OFIR (desk privado: lead + toxicity + mid-lag guard)
    if bool(cfg.get("fusion_enable_shadow", False)):
        q = maker_shadow_ofir(fair_up, best_bid, best_ask, spot, strike, cfg)
        if q is not None:
            return QuoteIntent(
                q.bid, q.ask, q.size_shares, "maker_fusion", f"via_shadow|{q.note}"
            )

    # 1) Pulse (latencia) — opcional; follow-heavy lo apaga (menos adverse @10).
    if bool(cfg.get("fusion_enable_pulse", True)):
        q = maker_pulse(fair_up, best_bid, best_ask, spot, strike, cfg)
        if q is not None:
            return QuoteIntent(
                q.bid, q.ask, q.size_shares, "maker_fusion", f"via_pulse|{q.note}"
            )

    # 2) Follow (unirse al mid informado + spot)
    if bool(cfg.get("fusion_enable_follow", True)):
        q = maker_follow(fair_up, best_bid, best_ask, spot, strike, cfg)
        if q is not None:
            return QuoteIntent(
                q.bid, q.ask, q.size_shares, "maker_fusion", f"via_follow|{q.note}"
            )

    # 3) Edge selectivo — solo con momentum alineado (si no, revive el fade tóxico).
    if bool(cfg.get("fusion_enable_edge", True)):
        edge_cfg = dict(cfg)
        edge_cfg["min_quote_mid"] = float(cfg.get("edge_min_quote_mid", 0.28) or 0.28)
        edge_cfg["max_quote_mid"] = float(cfg.get("edge_max_quote_mid", 0.72) or 0.72)
        edge_cfg["min_edge"] = float(cfg.get("edge_min_edge", cfg.get("min_edge", 0.028)) or 0.028)
        edge_cfg["cheap_side_only"] = bool(cfg.get("edge_cheap_side_only", True))
        edge_cfg["allow_rich_side"] = not edge_cfg["cheap_side_only"]
        edge_cfg["require_momentum_align"] = bool(
            cfg.get("edge_require_momentum", True)
        )
        q = maker_edge(fair_up, best_bid, best_ask, spot, strike, edge_cfg)
        if q is not None:
            return QuoteIntent(
                q.bid, q.ask, q.size_shares, "maker_fusion", f"via_edge|{q.note}"
            )
    return None


STRATEGIES = {
    "maker_16": maker_16,
    "wide_spread_probe": wide_spread_only,
    "tight_mid_fade": tight_mid_fade,
    "maker_edge": maker_edge,
    "maker_pulse": maker_pulse,
    "maker_follow": maker_follow,
    "maker_shadow_ofir": maker_shadow_ofir,
    "maker_fusion": maker_fusion,
}
