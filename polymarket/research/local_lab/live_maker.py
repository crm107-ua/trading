#!/usr/bin/env python3
"""
Live maker — órdenes GTC post-only reales (o DRY_RUN).

Gates: POLY_LIVE_ARMED, POLY_LIVE_DRY_RUN, POLY_LIVE_MAX_CAPITAL_USDC,
       POLY_SIGNATURE_TYPE / POLY_FUNDER_ADDRESS.

    python -m polymarket.research.local_lab.live_maker --config ... --minutes 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from polymarket.research.collectors.market_discovery import (
    discover_btc_5m_updown,
    pick_recording_targets,
    window_end,
    window_start,
)
from polymarket.research.local_lab.paper_maker import load_maker_cfg
from polymarket.research.local_lab.strategies import (
    STRATEGIES,
    apply_inventory_skew,
    pulse_spot_fair,
)
from polymarket.src.ai.decision_engine import decide_quote_action
from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.data.book_utils import best_bid_ask, top_size_imbalance
from polymarket.src.data.btc_spot import fetch_btc_spot_async
from polymarket.src.execution.clob_live import (
    MIN_BUY_NOTIONAL_USDC,
    MIN_ORDER_SHARES,
    ClobLiveClient,
    normalize_live_order,
    read_gates,
    round_inventory_size,
)
from polymarket.src.execution.live_policy import (
    day_loss_breached,
    record_session_pnl,
)

_DRY_SEQ = 0
from polymarket.src.pricing.fair_value import estimate_fair_values
from polymarket.src.signals.features import build_market_features

load_repo_dotenv()

ROOT = Path(__file__).resolve().parents[2]
OUT_BASE = ROOT / "data_local" / "local_lab"


@dataclass
class LiveFill:
    ts_ns: int
    side: str
    price: float
    size: float
    order_id: str | None
    market_id: str
    dry_run: bool


@dataclass
class LiveSession:
    cfg: dict[str, Any]
    out_dir: Path
    clob: ClobLiveClient
    bankroll: float
    strategy_id: str = "maker_fusion"
    inventory_shares: float = 0.0
    cost_basis: float = 0.0
    fills: list[LiveFill] = field(default_factory=list)
    quotes_logged: int = 0
    open_order_id: str | None = None
    open_side: str | None = None
    open_price: float | None = None
    open_size: float | None = None
    open_token_id: str | None = None
    last_quote_spot: float | None = None
    current_market_id: str | None = None
    strike: float | None = None
    strike_trusted: bool = False
    _strike_stamped: bool = False
    window_start_ns: int | None = None
    window_end_ns: int | None = None
    spot_history: list[tuple[int, float]] = field(default_factory=list)
    mid_history: list[tuple[int, float]] = field(default_factory=list)
    _pulse_streak: int = 0
    _decision_count: int = 0
    _last_progress_log: float = 0.0
    _session_start_mono: float = 0.0
    _entry_fills: int = 0
    _last_fill_mono: float = 0.0
    _seen_trade_ids: set[str] = field(default_factory=set)
    _seen_order_fills: set[str] = field(default_factory=set)
    _trade_after_ts: int | None = None
    _dry_posted_at: float = 0.0
    _exit_posted: bool = False
    _last_flatten_attempt: float = 0.0
    _flatten_fails: int = 0
    _dust_stuck: bool = False
    _halt_new_entries: bool = False
    position_leg: str | None = None  # "up" | "down" — qué token tenemos
    held_token_id: str | None = None  # token con inventario (persiste tras fill)
    realized_pnl: float = 0.0
    desk_line_id: int = 1
    _cash_bal: float | None = None
    _cash_bal_mono: float = 0.0
    _skip_cash_until: float = 0.0
    _coord_blocks: int = 0

    def _spot_delta_usd(self, window_ms: int = 3000) -> float:
        if len(self.spot_history) < 2:
            return 0.0
        now_ns = self.spot_history[-1][0]
        cutoff = now_ns - int(window_ms * 1e6)
        pts = [(t, s) for t, s in self.spot_history if t >= cutoff]
        if len(pts) < 2:
            pts = self.spot_history[-min(5, len(self.spot_history)) :]
        if len(pts) < 2:
            return 0.0
        return float(pts[-1][1] - pts[0][1])

    def _spot_velocity_usd(self, window_ms: int = 3000) -> float:
        return self._spot_delta_usd(window_ms)

    def _mid_delta(self, window_ms: int = 3000) -> float | None:
        if len(self.mid_history) < 2:
            return None
        now_ns = self.mid_history[-1][0]
        cutoff = now_ns - int(window_ms * 1e6)
        pts = [(t, m) for t, m in self.mid_history if t >= cutoff]
        if len(pts) < 2:
            return None
        return float(pts[-1][1] - pts[0][1])

    def _maybe_stamp_strike(self, spot: float) -> None:
        if self.window_start_ns is None:
            self.strike_trusted = False
            return
        age_s = (time.time_ns() - self.window_start_ns) / 1e9
        stamp_until = float(self.cfg.get("strike_stamp_max_age_s", 12) or 12)
        max_join = float(self.cfg.get("max_window_join_age_s", 50) or 50)
        if age_s < 0:
            self.strike_trusted = False
            self.cfg["_window_open"] = False
            return
        self.cfg["_window_open"] = True
        if not self._strike_stamped and age_s <= max_join:
            self.strike = float(spot)
            self._strike_stamped = True
        require_early = bool(self.cfg.get("pulse_require_early_strike", False))
        if require_early:
            self.strike_trusted = bool(self._strike_stamped and age_s <= stamp_until)
        else:
            self.strike_trusted = True

    def _inject_pulse_runtime(
        self,
        *,
        fair: float,
        spot: float,
        bids: list,
        asks: list,
        bb: float | None,
        ba: float | None,
        time_remaining_s: float | None,
    ) -> None:
        """Misma inyección runtime que paper_maker (Pulse/Follow/Shadow)."""
        if time_remaining_s is not None:
            self.cfg["_time_remaining_s"] = time_remaining_s
        self.cfg["_strike_trusted"] = bool(self.strike_trusted)
        vel_ms = int(self.cfg.get("pulse_velocity_window_ms", 3000) or 3000)
        roll_ms = int(self.cfg.get("pulse_roll_window_ms", 8000) or 8000)
        self.cfg["_spot_velocity_usd"] = self._spot_velocity_usd(vel_ms)
        self.cfg["_roll_lead_usd"] = self._spot_delta_usd(roll_ms)
        self.cfg["_mid_delta"] = self._mid_delta(roll_ms)
        self.cfg["_book_imbalance"] = top_size_imbalance(
            bids or [], asks or [], n=int(self.cfg.get("pulse_book_levels", 3) or 3)
        )
        roll = float(self.cfg["_roll_lead_usd"])
        vel = float(self.cfg["_spot_velocity_usd"])
        min_lead = float(self.cfg.get("min_spot_lead_usd", 12.0) or 12.0)
        min_vel = float(self.cfg.get("min_spot_velocity_usd", 4.0) or 4.0)
        min_edge = float(self.cfg.get("min_edge", 0.028) or 0.028)
        mid_lo = float(self.cfg.get("min_quote_mid", 0.38) or 0.38)
        mid_hi = float(self.cfg.get("max_quote_mid", 0.62) or 0.62)
        symmetric = bool(self.cfg.get("pulse_symmetric", True))
        mid_ok = False
        pulse_dir_ok = False
        if bb is not None and ba is not None:
            mid = (float(bb) + float(ba)) / 2.0
            mid_ok = mid_lo <= mid <= mid_hi
            scale = float(self.cfg.get("pulse_fair_scale_usd", 28.0) or 28.0)
            sf = pulse_spot_fair(float(spot), float(spot) - roll, scale)
            if bool(self.cfg.get("pulse_blend_bs_fair", True)):
                model_fair = max(float(fair), sf) if roll >= 0 else min(float(fair), sf)
            else:
                model_fair = sf
            edge = model_fair - mid
            up_ok = roll >= min_lead and vel >= min_vel and edge >= min_edge
            dn_ok = (
                symmetric
                and roll <= -min_lead
                and vel <= -min_vel
                and edge <= -min_edge
            )
            pulse_dir_ok = up_ok or dn_ok
        t_ok = True
        if time_remaining_s is not None:
            t_min = float(self.cfg.get("quote_time_min_s", 0) or 0)
            t_max = float(self.cfg.get("quote_time_max_s", 0) or 0)
            tr = float(time_remaining_s)
            if t_min > 0 and tr < t_min:
                t_ok = False
            if t_max > 0 and tr > t_max:
                t_ok = False
        pulse_agree = self.strike_trusted and mid_ok and pulse_dir_ok and t_ok
        follow_agree = False
        if bb is not None and ba is not None:
            mid_f = (float(bb) + float(ba)) / 2.0
            f_roll = float(self.cfg.get("follow_min_roll_usd", 1.5) or 1.5)
            f_vel = float(self.cfg.get("follow_min_vel_usd", 0.3) or 0.3)
            up_lo = float(self.cfg.get("follow_up_lo", 0.52) or 0.52)
            up_hi = float(self.cfg.get("follow_up_hi", 0.72) or 0.72)
            dn_lo = float(self.cfg.get("follow_dn_lo", 0.28) or 0.28)
            dn_hi = float(self.cfg.get("follow_dn_hi", 0.48) or 0.48)
            t_f_ok = True
            if time_remaining_s is not None:
                ft_min = float(self.cfg.get("follow_time_min_s", 80) or 80)
                ft_max = float(self.cfg.get("follow_time_max_s", 280) or 280)
                trf = float(time_remaining_s)
                if trf < ft_min or trf > ft_max:
                    t_f_ok = False
            if t_f_ok and up_lo <= mid_f <= up_hi and roll >= f_roll and vel >= f_vel:
                follow_agree = True
            elif (
                t_f_ok
                and dn_lo <= mid_f <= dn_hi
                and roll <= -f_roll
                and vel <= -f_vel
            ):
                follow_agree = True
        shadow_agree = False
        if bb is not None and ba is not None and (
            bool(self.cfg.get("fusion_enable_shadow", False))
            or self.strategy_id == "maker_shadow_ofir"
        ):
            mid_s = (float(bb) + float(ba)) / 2.0
            mid_d = self.cfg.get("_mid_delta")
            imb = self.cfg.get("_book_imbalance")
            s_lead = float(
                self.cfg.get("shadow_min_lead_usd", self.cfg.get("min_spot_lead_usd", 2.5))
                or 2.5
            )
            s_vel = float(
                self.cfg.get(
                    "shadow_min_vel_usd", self.cfg.get("min_spot_velocity_usd", 0.7)
                )
                or 0.7
            )
            max_md = float(self.cfg.get("shadow_max_mid_catchup", 0.018) or 0.018)
            min_imb = float(self.cfg.get("shadow_min_imbalance", 0.55) or 0.55)
            t_s_ok = True
            if time_remaining_s is not None:
                st_min = float(self.cfg.get("shadow_time_min_s", 90) or 90)
                st_max = float(self.cfg.get("shadow_time_max_s", 270) or 270)
                trs = float(time_remaining_s)
                if trs < st_min or trs > st_max:
                    t_s_ok = False
            if (
                t_s_ok
                and mid_d is not None
                and imb is not None
                and self.strike_trusted
            ):
                up_s = (
                    roll >= s_lead
                    and vel >= s_vel
                    and float(mid_d) <= max_md
                    and float(imb) >= min_imb
                )
                dn_s = (
                    roll <= -s_lead
                    and vel <= -s_vel
                    and float(mid_d) >= -max_md
                    and float(imb) <= (1.0 - min_imb)
                )
                shadow_agree = up_s or dn_s
                _ = mid_s  # mid_s usado implícitamente vía mid_d/imb gates
        if self.strategy_id == "maker_shadow_ofir" or (
            self.strategy_id == "maker_fusion"
            and bool(self.cfg.get("fusion_enable_shadow", False))
            and not bool(self.cfg.get("fusion_enable_pulse", True))
            and not bool(self.cfg.get("fusion_enable_follow", True))
        ):
            agree = shadow_agree
        elif self.strategy_id == "maker_follow" or (
            self.strategy_id == "maker_fusion"
            and not bool(self.cfg.get("fusion_enable_pulse", True))
        ):
            agree = follow_agree
        elif self.strategy_id == "maker_fusion":
            agree = pulse_agree or follow_agree or shadow_agree
        else:
            agree = pulse_agree
        self._pulse_streak = self._pulse_streak + 1 if agree else 0
        self.cfg["_pulse_streak"] = self._pulse_streak

    def _maker_quote(
        self,
        fair: float,
        bb: float | None,
        ba: float | None,
        spot: float,
        time_rem: float,
        *,
        bids: list | None = None,
        asks: list | None = None,
    ):
        self._inject_pulse_runtime(
            fair=fair,
            spot=spot,
            bids=bids or [],
            asks=asks or [],
            bb=bb,
            ba=ba,
            time_remaining_s=time_rem,
        )
        self.cfg["_runtime_size_scale"] = 1.0
        sid = self.strategy_id if self.strategy_id in STRATEGIES else "maker_fusion"
        fn = STRATEGIES[sid]
        raw = fn(fair, bb, ba, spot, self.strike or spot, self.cfg)
        if raw is None:
            return None
        mid = (bb + ba) / 2.0 if bb is not None and ba is not None else None
        return apply_inventory_skew(
            raw, inventory_shares=self.inventory_shares, cfg=self.cfg, mid=mid
        )

    async def _fetch_state(self, token_id: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=12.0) as client:
            try:
                spot, _src = await fetch_btc_spot_async(client)
            except RuntimeError:
                return None
            cr = await client.get(
                "https://clob.polymarket.com/book",
                params={"token_id": token_id},
            )
        if cr.status_code != 200:
            return None
        book = cr.json()
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        bb, ba = best_bid_ask(bids, asks)
        return {
            "spot": spot,
            "bids": bids,
            "asks": asks,
            "best_bid": bb,
            "best_ask": ba,
            "feed_ts_ms": int(time.time() * 1000),
        }

    async def _refresh_cash(self, *, force: bool = False) -> float:
        now = time.monotonic()
        if (
            not force
            and self._cash_bal is not None
            and (now - self._cash_bal_mono) < 5.0
        ):
            return float(self._cash_bal)
        # Sim CLOB con dinero ficticio: libro/red reales, caja virtual.
        if self.clob.gates.dry_run:
            virt = os.getenv("POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC")
            if virt:
                try:
                    self._cash_bal = float(virt)
                    self._cash_bal_mono = now
                    return float(self._cash_bal)
                except ValueError:
                    pass
        try:
            bal = await asyncio.to_thread(self.clob.balance_collateral_usdc)
            self._cash_bal = float(bal)
            self._cash_bal_mono = now
            return float(bal)
        except Exception as e:
            # Dry / blips de red: no tumbar la sesión; usa cache o capital cfg.
            fallback = self._cash_bal
            if fallback is None:
                fallback = float(
                    self.cfg.get("initial_capital_usdc") or self.bankroll or 0.0
                )
            print(
                f"CASH_REFRESH_ERR {type(e).__name__}: {e} "
                f"fallback={float(fallback):.4f} dry={self.clob.gates.dry_run}",
                flush=True,
            )
            if self._cash_bal is None:
                self._cash_bal = float(fallback)
                self._cash_bal_mono = now
            return float(self._cash_bal)

    async def _cancel_stale_open_orders(self) -> None:
        """Cancela órdenes huérfanas (p.ej. SELL dust @0.01 de sesiones previas)."""
        try:
            orders = await asyncio.to_thread(self.clob.open_orders)
        except Exception as e:
            print(f"OPEN_ORDERS_ERR {type(e).__name__}: {e}", flush=True)
            return
        for o in orders or []:
            if not isinstance(o, dict):
                continue
            oid = str(o.get("id") or o.get("orderID") or "")
            if not oid:
                continue
            side = str(o.get("side") or "").upper()
            try:
                px = float(o.get("price") or 0)
            except (TypeError, ValueError):
                px = 0.0
            # Dust exits / basura que no libera nada útil
            if side == "SELL" and px <= 0.02:
                try:
                    await asyncio.to_thread(self.clob.cancel, oid)
                    print(f"CANCEL_STALE {side}@{px} order={oid[:18]}…", flush=True)
                except Exception as e:
                    print(f"CANCEL_STALE_ERR {type(e).__name__}: {e}", flush=True)

    def _progress(self, minutes: float, last: str) -> None:
        now = time.monotonic()
        if now - self._last_progress_log < 8.0:
            return
        self._last_progress_log = now
        elapsed = (now - self._session_start_mono) / 60.0
        pct = min(99.9, round(100.0 * elapsed / minutes, 1)) if minutes > 0 else 0.0
        mode = "DRY" if self.clob.gates.dry_run else "LIVE"
        print(
            f"paper {pct}% [{elapsed:.1f}/{minutes:.1f} min] "
            f"decisions={self._decision_count} quotes={self.quotes_logged} "
            f"fills={len(self.fills)} last={last} ({mode})",
            flush=True,
        )

    async def _cancel_open(self, *, reason: str = "") -> None:
        if not self.open_order_id:
            return
        # Sync first — no cancel si ya MATCHED
        await self._poll_fills(self.open_token_id or "")
        if not self.open_order_id:
            return
        try:
            await asyncio.to_thread(self.clob.cancel, self.open_order_id)
            print(
                f"CANCEL order={self.open_order_id}"
                + (f" reason={reason}" if reason else ""),
                flush=True,
            )
        except Exception as e:
            print(f"CANCEL_ERR {type(e).__name__}: {e}", flush=True)
        self.open_order_id = None
        self.open_side = None
        self.open_price = None
        self.open_size = None

    async def _post_quote(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        *,
        best_bid: float | None = None,
        best_ask: float | None = None,
    ) -> None:
        if self.open_order_id:
            await self._cancel_open(reason="replace")
        # Post-only: BUY must stay below ask; SELL above bid
        px = float(price)
        side_u = side.upper()
        if side_u == "BUY" and best_ask is not None:
            px = min(px, float(best_ask) - 0.01)
        if side_u == "SELL" and best_bid is not None:
            # join bid (puede ser = bid; post-only OK si no cruza)
            px = min(px, float(best_bid))
            if best_ask is not None:
                px = min(px, float(best_ask) - 0.01)
        if side_u == "SELL":
            # Nunca vender más de lo que hay (fill parcial 4.99 ≠ bump a 5)
            avail = round_inventory_size(min(abs(size), abs(self.inventory_shares)))
            if avail <= 0:
                print("SKIP_SELL no inventory", flush=True)
                return
            if avail + 1e-9 < MIN_ORDER_SHARES:
                print(
                    f"SKIP_SELL dust inv={avail:.6f} < min={MIN_ORDER_SHARES} "
                    "(CLOB rechaza; hace falta top-up o redeem)",
                    flush=True,
                )
                self._flatten_fails += 1
                self._last_flatten_attempt = time.monotonic()
                return
            px, sz = normalize_live_order(side="SELL", price=px, size=avail, tick=0.01)
            if sz > avail:
                sz = avail
        else:
            px, sz = normalize_live_order(side="BUY", price=px, size=size, tick=0.01)
        max_notional = float(self.cfg.get("max_notional_per_side_usdc") or 5.0)
        if side_u == "BUY" and px * sz > max_notional + 1e-9:
            print(
                f"SKIP_BUDGET need={px * sz:.2f} max_notional={max_notional:.2f} "
                f"(min shares={MIN_ORDER_SHARES})",
                flush=True,
            )
            return
        if side_u == "BUY" and px * sz < MIN_BUY_NOTIONAL_USDC:
            print(f"SKIP_MIN_NOTIONAL {px * sz:.2f} < {MIN_BUY_NOTIONAL_USDC}", flush=True)
            return
        if side_u == "BUY":
            # Enforzar caja también en DRY (preflight realista antes de micro).
            now_m = time.monotonic()
            if now_m < self._skip_cash_until:
                return
            cash = await self._refresh_cash(force=False)
            need = px * sz
            # Buffer 2¢ por redondeos CLOB
            if need > cash - 0.02:
                max_px = max(0.01, (cash - 0.02) / max(sz, MIN_ORDER_SHARES))
                print(
                    f"SKIP_CASH need={need:.2f} bal={cash:.4f} "
                    f"(5sh solo si px<={max_px:.2f})",
                    flush=True,
                )
                self._skip_cash_until = now_m + 8.0
                return
        try:
            resp = await asyncio.to_thread(
                self.clob.place_post_only_gtc,
                token_id=token_id,
                side=side_u,
                price=px,
                size=sz,
            )
        except Exception as e:
            msg = str(e)
            print(f"POST_ERR {type(e).__name__}: {e}", flush=True)
            if side_u == "SELL":
                self._flatten_fails += 1
                self._last_flatten_attempt = time.monotonic()
            if "balance is not enough" in msg.lower() or "not enough balance" in msg.lower():
                await self._refresh_cash(force=True)
                self._skip_cash_until = time.monotonic() + 12.0
            # Geoblock: no tiene sentido seguir 15 min con señales y 0 posts.
            if (
                "trading restricted in your region" in msg.lower()
                or "geoblock" in msg.lower()
                or ("status_code=403" in msg and "region" in msg.lower())
            ):
                self._halt_new_entries = True
                print(
                    "GEOBLOCK_KILL — IP/región bloqueada por Polymarket; "
                    "abortando nuevas entradas (SAFE al salir).",
                    flush=True,
                )
            return
        oid = resp.get("orderID")
        st = resp.get("status")
        wp = resp.get("would_post") or {}
        px = float(wp.get("price") or px)
        sz = float(wp.get("size") or sz)
        if st == "DRY_RUN" and not oid:
            global _DRY_SEQ
            _DRY_SEQ += 1
            oid = f"dry-{_DRY_SEQ}"
            self._dry_posted_at = time.monotonic()
        print(
            f"POST {st} {side} px={px:.2f} sz={sz:.2f} notional={px*sz:.2f} "
            f"order={oid} payload={wp}",
            flush=True,
        )
        self.quotes_logged += 1
        self.open_order_id = oid
        self.open_side = side.upper()
        self.open_price = px
        self.open_size = sz
        self.open_token_id = token_id
        if side.upper() == "SELL":
            self._exit_posted = True

    @staticmethod
    def _is_cheap_quote(quote) -> bool:
        """Lado barato Up: bid activo, ask fantasma alta."""
        return bool(
            quote
            and quote.bid
            and float(quote.bid) > 0.015
            and (quote.ask is None or float(quote.ask) >= 0.98)
        )

    @staticmethod
    def _is_rich_quote(quote) -> bool:
        """Lado rico Up: ask activa, bid fantasma baja → en live = BUY Down."""
        return bool(
            quote
            and quote.ask
            and float(quote.ask) < 0.985
            and (quote.bid is None or float(quote.bid) <= 0.02)
        )

    def _desk_role(self) -> str:
        return str(self.cfg.get("desk_role") or "pulse").strip().lower()

    def _coord_mode(self) -> str:
        return str(
            self.cfg.get("desk_coord_mode")
            or os.getenv("POLY_DESK_COORD_MODE")
            or "mutex_market"
        ).strip().lower()

    def _try_desk_claim(self, target: Any, direction: str) -> bool:
        """Anti-colisión: veto central antes de postear entrada."""
        if not bool(self.cfg.get("desk_coord_enable", True)):
            return True
        from polymarket.research.local_lab.desk_coordinator import try_claim

        mid = str(getattr(target, "market_id", None) or self.current_market_id or "")
        res = try_claim(
            line_id=int(self.desk_line_id),
            market_id=mid,
            direction=direction,
            mode=self._coord_mode(),
            role=self._desk_role(),
            window_start_ns=self.window_start_ns,
        )
        if not res.ok:
            self._coord_blocks += 1
            print(
                f"COORD_BLOCK mode={self._coord_mode()} reason={res.reason} "
                f"line={self.desk_line_id} mid={mid[:18]}…",
                flush=True,
            )
            return False
        return True

    async def _post_entry(
        self,
        target: Any,
        quote: Any,
        *,
        bb: float | None,
        ba: float | None,
        fair_up: float,
    ) -> str:
        """Entra BUY Up (cheap) o BUY Down (rich). Devuelve last= tag."""
        # Ensemble role: solo filtra si role ∈ {pulse,follow,shadow}.
        # "fusion"/"any"/"" → deja pasar pulse+follow (micro compound).
        role = self._desk_role()
        note = str(getattr(quote, "note", "") or "").lower()
        if role in ("pulse", "follow", "shadow"):
            if role == "pulse" and "follow" in note and "pulse" not in note:
                return "role_skip_follow"
            if role == "follow" and "pulse" in note and "follow" not in note:
                return "role_skip_pulse"
            if role == "shadow" and "shadow" not in note:
                return "role_skip_noshadow"

        direction = "up" if self._is_cheap_quote(quote) else "down"
        if not self._try_desk_claim(target, direction):
            return "coord_block"

        sz = max(float(quote.size_shares), MIN_ORDER_SHARES)
        # Cluster sizing: N clones correlacionados ⇒ size_scale = N_eff/N
        try:
            from polymarket.research.local_lab.desk_coordinator import size_scale_for_cluster

            n_lines = int(self.cfg.get("desk_cluster_lines") or 1)
            rho = float(self.cfg.get("desk_cluster_rho") or 0.85)
            if n_lines > 1 and self._coord_mode() not in ("mutex_market", "window_slot"):
                sz = max(MIN_ORDER_SHARES, round(sz * size_scale_for_cluster(n_lines, rho), 2))
        except Exception:
            pass
        allow_rich = bool(self.cfg.get("allow_rich_side_live", True))
        if self._is_cheap_quote(quote):
            await self._post_quote(
                target.token_id_up,
                "BUY",
                float(quote.bid),
                sz,
                best_bid=bb,
                best_ask=ba,
            )
            if self.open_order_id and self.open_side == "BUY":
                self.position_leg = "up"
                self.held_token_id = str(target.token_id_up)
                return "quote_up"
            return "post_fail_up"
        if allow_rich and self._is_rich_quote(quote) and getattr(target, "token_id_down", None):
            # Complementario: vender Up caro ≡ comprar Down barato
            down_id = str(target.token_id_down)
            st_dn = await self._fetch_state(down_id)
            if st_dn is None or st_dn.get("best_bid") is None:
                return "skip_down_book"
            dn_bb = float(st_dn["best_bid"])
            dn_ba = float(st_dn["best_ask"]) if st_dn.get("best_ask") is not None else None
            # Precio maker en Down ≈ 1 - ask_up, anclado al book Down
            px = min(dn_bb, max(0.01, round(1.0 - float(quote.ask), 2)))
            if dn_ba is not None:
                px = min(px, float(dn_ba) - 0.01)
            if px <= 0.015:
                return "skip_down_px"
            print(
                f"ENTRY_RICH via DOWN px={px:.2f} (up_ask={float(quote.ask):.2f} "
                f"fair_up={fair_up:.3f})",
                flush=True,
            )
            await self._post_quote(
                down_id,
                "BUY",
                px,
                sz,
                best_bid=dn_bb,
                best_ask=dn_ba,
            )
            if self.open_order_id and self.open_side == "BUY":
                self.position_leg = "down"
                self.held_token_id = down_id
                return "quote_down"
            return "post_fail_down"
        return "skip_rich_side"

    def _record_fill(
        self,
        side: str,
        price: float,
        size: float,
        order_id: str | None,
        *,
        dry: bool,
    ) -> None:
        oid = str(order_id or "")
        if oid and oid in self._seen_order_fills:
            return
        if oid:
            self._seen_order_fills.add(oid)
        side_u = side.upper()
        if side_u == "BUY":
            self.inventory_shares = round_inventory_size(self.inventory_shares + size)
            self.cost_basis += price * size
            self._entry_fills += 1
            self._exit_posted = False
            self._flatten_fails = 0
            # Crítico: no perder el token al limpiar open_order_* tras MATCHED
            if self.open_token_id:
                self.held_token_id = str(self.open_token_id)
        else:
            if self.inventory_shares > 1e-9:
                avg = self.cost_basis / self.inventory_shares
                sold = min(size, self.inventory_shares)
                pnl = (price - avg) * sold
                self.realized_pnl += pnl
                self.bankroll += pnl
                self.inventory_shares -= sold
                self.cost_basis = avg * self.inventory_shares if self.inventory_shares > 1e-9 else 0.0
            else:
                self.inventory_shares = 0.0
                self.cost_basis = 0.0
            if self.inventory_shares < 1e-9:
                self._exit_posted = False
                self.position_leg = None
                self.held_token_id = None
        self.fills.append(
            LiveFill(
                ts_ns=time.time_ns(),
                side=side_u,
                price=price,
                size=size,
                order_id=order_id,
                market_id=self.current_market_id or "",
                dry_run=dry,
            )
        )
        self._last_fill_mono = time.monotonic()
        tag = "DRY_FILL" if dry else "FILL"
        print(
            f"{tag} {side_u} px={price:.3f} sz={size:.2f} "
            f"inv={self.inventory_shares:.2f} realized={self.realized_pnl:+.2f} "
            f"bankroll={self.bankroll:.2f}",
            flush=True,
        )
        # Clear resting order if this fill closes it
        if oid and self.open_order_id and oid == self.open_order_id:
            self.open_order_id = None
            self.open_side = None
            self.open_price = None
            self.open_size = None

    async def _poll_fills(self, token_id: str) -> None:
        # 1) Dry: simular fill ~2s después del POST (para probar exit)
        if self.clob.gates.dry_run and self.open_order_id and str(self.open_order_id).startswith("dry-"):
            if self._dry_posted_at and (time.monotonic() - self._dry_posted_at) >= 2.0:
                self._record_fill(
                    self.open_side or "BUY",
                    float(self.open_price or 0),
                    float(self.open_size or 0),
                    self.open_order_id,
                    dry=True,
                )
            return

        # 2) get_order → MATCHED (fuente más fiable)
        if self.open_order_id and not str(self.open_order_id).startswith("dry-"):
            order = await asyncio.to_thread(self.clob.get_order, self.open_order_id)
            fill = ClobLiveClient.fill_from_order(order) if order else None
            if fill and fill["size"] > 0:
                status = str(fill.get("status") or "").upper()
                matched = float(fill["size"])
                if status == "MATCHED" or matched >= float(self.open_size or matched) - 1e-9:
                    side = fill["side"] or self.open_side or "BUY"
                    self._record_fill(side, fill["price"], matched, fill["order_id"], dry=False)

        # 3) trades (puede venir en asset complementario)
        try:
            trades = await asyncio.to_thread(self.clob.recent_trades, None, self._trade_after_ts)
        except Exception as e:
            print(f"TRADES_ERR {type(e).__name__}: {e}", flush=True)
            return
        our_ids = set(self._seen_order_fills)
        if self.open_order_id:
            our_ids.add(self.open_order_id)
        # Also any order we posted this session from fills list
        for f in self.fills:
            if f.order_id:
                our_ids.add(f.order_id)
        detected = ClobLiveClient.fills_from_trades(trades or [], our_ids)
        for d in detected:
            tid = d.get("trade_id") or ""
            if tid and tid in self._seen_trade_ids:
                continue
            if tid:
                self._seen_trade_ids.add(tid)
            oid = d.get("order_id") or ""
            if oid and oid in self._seen_order_fills:
                continue
            side = d.get("side") or self.open_side or "BUY"
            # Precio de nuestra orden maker si lo tenemos
            px = float(d["price"])
            if self.open_price and oid == self.open_order_id:
                px = float(self.open_price)
            self._record_fill(side, px, float(d["size"]), oid or None, dry=False)

    async def _topup_dust_to_min(
        self,
        token_id: str,
        *,
        best_ask: float | None,
    ) -> bool:
        """Si inv < 5, compra el mínimo CLOB para poder vender después.
        Devuelve True si el inventario queda >= MIN_ORDER_SHARES."""
        inv = round_inventory_size(self.inventory_shares)
        if inv + 1e-9 >= MIN_ORDER_SHARES:
            return True
        if self._dust_stuck:
            return False
        # Precio para notional >= $1 con size=5
        ask = float(best_ask) if best_ask is not None else 0.5
        px = max(ask, MIN_BUY_NOTIONAL_USDC / MIN_ORDER_SHARES)
        px = min(0.99, max(0.01, round(px, 2)))
        print(
            f"DUST_TOPUP buy {MIN_ORDER_SHARES:.0f}@{px:.2f} "
            f"(inv={inv:.6f} < {MIN_ORDER_SHARES})",
            flush=True,
        )
        try:
            resp = await asyncio.to_thread(
                self.clob.place_aggressive,
                token_id=token_id,
                side="BUY",
                price=px,
                size=MIN_ORDER_SHARES,
                order_type="FAK",
            )
        except Exception as e:
            print(f"DUST_TOPUP_ERR {type(e).__name__}: {e}", flush=True)
            self._dust_stuck = True
            self._halt_new_entries = True
            return False
        st = resp.get("status")
        wp = resp.get("would_post") or {}
        if st == "DRY_RUN":
            self._record_fill(
                "BUY",
                float(wp.get("price") or px),
                float(wp.get("size") or MIN_ORDER_SHARES),
                None,
                dry=True,
            )
            return self.inventory_shares + 1e-9 >= MIN_ORDER_SHARES
        oid = resp.get("orderID")
        # Poll order once for fill size
        if oid:
            order = await asyncio.to_thread(self.clob.get_order, oid)
            fill = ClobLiveClient.fill_from_order(order) if order else None
            if fill and fill["size"] > 0:
                self._record_fill(
                    "BUY", fill["price"], fill["size"], fill["order_id"], dry=False
                )
        ok = self.inventory_shares + 1e-9 >= MIN_ORDER_SHARES
        if not ok:
            print(
                f"DUST_STUCK inv={self.inventory_shares:.6f} tras top-up; "
                "halt entradas — redeem manual si mercado muere",
                flush=True,
            )
            self._dust_stuck = True
            self._halt_new_entries = True
        return ok

    async def _force_flatten(
        self,
        token_id: str,
        *,
        best_bid: float | None,
        best_ask: float | None,
        reason: str,
    ) -> None:
        if abs(self.inventory_shares) < 1e-9:
            return
        # Evitar spam de POST_ERR cada tick
        now = time.monotonic()
        if self._dust_stuck:
            if int(now) % 30 == 0:
                print(
                    f"DUST_STUCK inv={self.inventory_shares:.6f} — no más flatten spam",
                    flush=True,
                )
            return
        if self._flatten_fails >= 2 and (now - self._last_flatten_attempt) < 30.0:
            if int(now) % 30 == 0:
                print(
                    f"FLATTEN_BACKOFF fails={self._flatten_fails} inv={self.inventory_shares:.6f}",
                    flush=True,
                )
            return
        if self.open_side == "SELL" and self.open_order_id:
            return  # ya hay exit resting
        # Siempre vender el token que realmente tenemos (no el Up por defecto)
        sell_tid = str(self.held_token_id or self.open_token_id or token_id)
        print(
            f"FLATTEN reason={reason} inv={self.inventory_shares:.6f} "
            f"token={sell_tid[:18]}… leg={self.position_leg}",
            flush=True,
        )
        self._last_flatten_attempt = now
        # Verificar balance CLOB del condicional (evita SELL al token equivocado)
        try:
            clob_bal = await asyncio.to_thread(
                self.clob.balance_conditional_shares, sell_tid
            )
        except Exception as e:
            print(f"BAL_COND_ERR {type(e).__name__}: {e}", flush=True)
            clob_bal = 0.0
        if clob_bal < 0.01:
            # Dry: no hay tokens reales — sintetizar SELL y limpiar inventario simulado.
            if self.clob.gates.dry_run and abs(self.inventory_shares) > 1e-9:
                px_dry = (
                    float(best_bid)
                    if best_bid is not None
                    else (float(best_ask) - 0.01 if best_ask is not None else 0.40)
                )
                px_dry = max(0.01, min(0.99, px_dry))
                print(
                    f"FLATTEN_DRY_CLEAR inv={self.inventory_shares:.4f} "
                    f"px={px_dry:.2f} (sin tokens reales)",
                    flush=True,
                )
                self._record_fill(
                    "SELL",
                    px_dry,
                    abs(self.inventory_shares),
                    None,
                    dry=True,
                )
                self._flatten_fails = 0
                return
            print(
                f"FLATTEN_WRONG_TOKEN bal=0 token={sell_tid[:24]}… "
                f"held={str(self.held_token_id)[:24] if self.held_token_id else None}",
                flush=True,
            )
            self._flatten_fails += 1
            return
        inv = round_inventory_size(min(abs(self.inventory_shares), clob_bal))
        if inv + 1e-9 < MIN_ORDER_SHARES:
            topped = await self._topup_dust_to_min(sell_tid, best_ask=best_ask)
            if not topped:
                self._flatten_fails += 1
                return
            inv = round_inventory_size(
                min(
                    abs(self.inventory_shares),
                    await asyncio.to_thread(
                        self.clob.balance_conditional_shares, sell_tid
                    ),
                )
            )
        # Book del token correcto (si nos pasaron bid de otro leg, refetch)
        if sell_tid != str(token_id) or best_bid is None:
            st = await self._fetch_state(sell_tid)
            if st:
                best_bid = st.get("best_bid")
                best_ask = st.get("best_ask")
        if best_bid is not None:
            px = float(best_bid)
        elif best_ask is not None:
            px = max(0.01, float(best_ask) - 0.01)
        else:
            px = 0.01
        # Salida agresiva (FAK) si hay bid; si no, GTC resting (no FAK vacío)
        try:
            ot = "FAK" if best_bid is not None else "GTC"
            resp = await asyncio.to_thread(
                self.clob.place_aggressive,
                token_id=sell_tid,
                side="SELL",
                price=max(0.01, px),
                size=inv,
                order_type=ot,
            )
            st = resp.get("status")
            wp = resp.get("would_post") or {}
            oid = resp.get("orderID")
            print(
                f"POST_EXIT {st} SELL px={wp.get('price', px)} sz={wp.get('size', inv)} "
                f"order={oid}",
                flush=True,
            )
            if st == "DRY_RUN":
                self._record_fill(
                    "SELL",
                    float(wp.get("price") or px),
                    float(wp.get("size") or inv),
                    None,
                    dry=True,
                )
                self._flatten_fails = 0
                return
            if oid:
                order = await asyncio.to_thread(self.clob.get_order, oid)
                fill = ClobLiveClient.fill_from_order(order) if order else None
                if fill and fill["size"] > 0:
                    self._record_fill(
                        "SELL", fill["price"], fill["size"], fill["order_id"], dry=False
                    )
                    self._flatten_fails = 0
                    return
        except Exception as e:
            print(f"EXIT_FAK_ERR {type(e).__name__}: {e}", flush=True)
        await self._post_quote(
            sell_tid,
            "SELL",
            px,
            inv,
            best_bid=best_bid,
            best_ask=best_ask,
        )
        if self.open_side == "SELL" and self.open_order_id:
            self._flatten_fails = 0  # post aceptado
        else:
            self._flatten_fails += 1

    def _position_token(self, up_id: str) -> str:
        """Token con inventario: held > open > up (nunca adivinar Up tras fill Down)."""
        if abs(self.inventory_shares) < 1e-9:
            return up_id
        return str(self.held_token_id or self.open_token_id or up_id)

    def _session_loss_kill(self) -> bool:
        """Stop duro Fase D: session_kill_net o pérdida diaria."""
        lim = float(self.cfg.get("session_kill_net_usdc") or 0.40)
        if self.realized_pnl <= -abs(lim) + 1e-12:
            print(
                f"KILL_SESSION realized={self.realized_pnl:.2f} limit=-{abs(lim):.2f}",
                flush=True,
            )
            self._halt_new_entries = True
            return True
        if day_loss_breached(self.realized_pnl):
            print(
                f"KILL_DAY session_realized={self.realized_pnl:.2f}",
                flush=True,
            )
            self._halt_new_entries = True
            return True
        return False

    def _fusionish(self) -> bool:
        label_l = str(self.cfg.get("demo_label", "")).lower()
        return bool(self.cfg.get("preserve_selectivity")) or any(
            x in label_l
            for x in (
                "fusion",
                "follow",
                "flow",
                "pulse",
                "bank",
                "promo",
                "shadow",
                "ofir",
            )
        )

    async def _maybe_exit(
        self,
        token_id: str,
        mid: float,
        fair: float,
        *,
        best_bid: float | None,
        best_ask: float | None,
        time_rem: float,
    ) -> None:
        if abs(self.inventory_shares) < 1e-9:
            return
        # Mark ejecutable (bid si long) — alineado con paper fusionish.
        mark = float(best_bid) if best_bid is not None else float(mid)
        lock = float(self.cfg.get("lock_profit_usdc") or 0.15)
        lock = min(lock, 0.20)
        max_loss = min(float(self.cfg.get("max_loss_usdc") or 0.5), 0.35)
        avg = self.cost_basis / self.inventory_shares
        unreal = self.inventory_shares * mark - self.cost_basis
        flatten_s = float(self.cfg.get("flatten_before_window_s") or 45)
        urgent = time_rem <= flatten_s
        bank_at = float(self.cfg.get("grind_bank_usdc", 0) or 0)
        green_at = min(bank_at, lock) if bank_at > 0 and lock > 0 else (bank_at or lock)
        hard_bank = float(self.cfg.get("hard_bank_usdc", 0) or 0)
        if self._fusionish() and hard_bank <= 0:
            hard_bank = max(green_at * 2.5, 0.08) if green_at > 0 else 0.08
        take = unreal >= (green_at if self._fusionish() and green_at > 0 else lock)
        hard_take = self._fusionish() and hard_bank > 0 and unreal >= hard_bank
        # soft/abs cut en USDC — el viejo -0.01 mataba micros de 5sh al primer tick
        # (5 × −0.002 mid = −0.01). Escalar por inventario o cfg.
        inv_abs = max(abs(self.inventory_shares), 1.0)
        soft_cut_usdc = float(self.cfg.get("soft_cut_usdc") or 0)
        if soft_cut_usdc <= 0:
            soft_cut_usdc = max(0.03, 0.008 * inv_abs)
        abs_cut_usdc = float(self.cfg.get("abs_cut_usdc") or 0)
        if abs_cut_usdc <= 0:
            abs_cut_usdc = max(0.06, 0.012 * inv_abs)
        soft_cut = self._fusionish() and unreal <= -soft_cut_usdc
        abs_cut = self._fusionish() and unreal <= -abs_cut_usdc
        stop = unreal <= -max_loss * (0.35 if self._fusionish() else 1.0)
        fade = fair < avg - 0.015
        # No “quick” por debajo del bank fusionish — mataba PnL al escalar size.
        if self._fusionish() and green_at > 0:
            quick = unreal >= max(green_at, 0.05) and time_rem < 100
        else:
            quick = unreal >= 0.05 or (
                self._entry_fills > 0 and unreal >= 0.02 and time_rem < 120
            )
        if urgent or take or hard_take or soft_cut or abs_cut or stop or fade or quick:
            if self.open_side == "SELL" and self.open_order_id and not urgent:
                return
            reason = (
                "urgent"
                if urgent
                else "hard_bank"
                if hard_take
                else "bank"
                if take
                else "soft_cut"
                if soft_cut
                else "abs_cut"
                if abs_cut
                else "sl"
                if stop
                else "fade"
                if fade
                else "quick"
            )
            await self._force_flatten(
                token_id, best_bid=best_bid, best_ask=best_ask, reason=reason
            )

    async def run(self, minutes: float = 5.0) -> dict[str, Any]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._session_start_mono = time.monotonic()
        self._trade_after_ts = int(time.time()) - 30
        gates = self.clob.gates
        print(
            f"Live OUT: {self.out_dir} armed={gates.armed} dry_run={gates.dry_run} "
            f"sig={gates.signature_type} funder={gates.funder}",
            flush=True,
        )
        bal = await self._refresh_cash(force=True)
        cap = float(self.cfg.get("initial_capital_usdc") or bal)
        max_n = float(self.cfg.get("max_notional_per_side_usdc") or cap)
        max_px = (min(bal, max_n) - 0.02) / MIN_ORDER_SHARES
        print(
            f"balance_pusd={bal:.4f} capital_cap={cap} max_notional={max_n:.2f} "
            f"max_buy_px≈{max_px:.2f} (min {MIN_ORDER_SHARES:.0f}sh)",
            flush=True,
        )
        if (not gates.dry_run) and bal < MIN_BUY_NOTIONAL_USDC:
            raise RuntimeError(
                f"Saldo CLOB insuficiente para min BUY ${MIN_BUY_NOTIONAL_USDC:.0f}: "
                f"{bal:.4f} pUSD"
            )
        if not gates.dry_run:
            await self._cancel_stale_open_orders()
            # Si capital UI > cash real, recortar notional al cash
            if bal + 1e-9 < max_n:
                self.cfg["max_notional_per_side_usdc"] = round(max(1.0, bal * 0.98), 2)
                print(
                    f"CAP_TO_CASH max_notional→{self.cfg['max_notional_per_side_usdc']}",
                    flush=True,
                )

        end_at = time.monotonic() + minutes * 60
        poll_s = 1.2
        requote_move = float(self.cfg.get("requote_spot_move_usd") or 9)
        fills_path = self.out_dir / "fills.jsonl"
        smoke_done = False

        try:
            while time.monotonic() < end_at:
                markets = await asyncio.to_thread(discover_btc_5m_updown)
                now = datetime.now(timezone.utc)
                active, nxt = pick_recording_targets(markets, now)
                target = active or nxt
                if target is None:
                    self._progress(minutes, "wait_market")
                    await asyncio.sleep(poll_s)
                    continue

                # Smoke sizing: por defecto solo log (no contaminar inventario dry).
                # Opt-in post: POLY_LIVE_DRY_SMOKE_POST=1
                if not smoke_done:
                    smoke_done = True
                    state0 = await self._fetch_state(target.token_id_up)
                    bb0 = state0["best_bid"] if state0 else 0.40
                    ba0 = state0["best_ask"] if state0 else 0.60
                    smoke_px = 0.40
                    if bb0 is not None and ba0 is not None:
                        mid0 = (float(bb0) + float(ba0)) / 2.0
                        smoke_px = min(0.55, max(0.25, min(float(bb0), mid0 - 0.01)))
                    n_px, n_sz = normalize_live_order(
                        side="BUY", price=smoke_px, size=1.0, tick=0.01
                    )
                    print(
                        f"SMOKE_SIZE min_shares={MIN_ORDER_SHARES} "
                        f"min_buy_notional={MIN_BUY_NOTIONAL_USDC} "
                        f"1share@{smoke_px:.2f} -> px={n_px:.2f} sz={n_sz:.2f} "
                        f"notional={n_px*n_sz:.2f}",
                        flush=True,
                    )
                    smoke_post = (os.getenv("POLY_LIVE_DRY_SMOKE_POST") or "0").strip() == "1"
                    if gates.dry_run and smoke_post:
                        await self._post_quote(
                            target.token_id_up,
                            "BUY",
                            smoke_px,
                            1.0,
                            best_bid=bb0,
                            best_ask=ba0,
                        )

                if target.market_id != self.current_market_id:
                    # Antes de rotar: intentar flatten inventario (nunca llevar a resolución)
                    if abs(self.inventory_shares) > 1e-9 and self.open_token_id:
                        st_old = await self._fetch_state(self.open_token_id)
                        if st_old:
                            await self._force_flatten(
                                self.open_token_id,
                                best_bid=st_old.get("best_bid"),
                                best_ask=st_old.get("best_ask"),
                                reason="market_roll",
                            )
                            await self._poll_fills(self.open_token_id)
                    await self._cancel_open(reason="market_roll")
                    self.current_market_id = target.market_id
                    ws = window_start(target)
                    we = window_end(target)
                    self.window_start_ns = int(ws.timestamp() * 1e9) if ws else None
                    self.window_end_ns = int(we.timestamp() * 1e9) if we else None
                    self._strike_stamped = False
                    self.strike_trusted = False
                    self._pulse_streak = 0
                    self.spot_history.clear()
                    self.mid_history.clear()
                    async with httpx.AsyncClient(timeout=12.0) as c:
                        self.strike, _src = await fetch_btc_spot_async(c)
                    self.last_quote_spot = None
                    print(
                        f"MARKET strat={self.strategy_id} {target.question[:80]}",
                        flush=True,
                    )

                # Señales siempre sobre libro UP; posición puede ser UP o DOWN
                up_id = target.token_id_up
                state_up = await self._fetch_state(up_id)
                if state_up is None:
                    await asyncio.sleep(poll_s)
                    continue

                # Poll ANTES de fijar pos_id: un fill Down no debe exit sobre Up
                await self._poll_fills(self.open_token_id or up_id)
                if self.open_order_id and self.open_token_id:
                    await self._poll_fills(self.open_token_id)

                pos_id = self._position_token(up_id)
                state = state_up
                if pos_id != up_id:
                    state_pos = await self._fetch_state(pos_id)
                    if state_pos is not None:
                        state = state_pos
                # Inferir leg si tenemos held Down pero position_leg vacío
                if (
                    abs(self.inventory_shares) > 1e-9
                    and self.position_leg is None
                    and pos_id != up_id
                ):
                    self.position_leg = "down"

                we_ns = self.window_end_ns or time.time_ns()
                time_rem = max((we_ns - time.time_ns()) / 1e9, 1.0)
                now_ns = time.time_ns()
                self.spot_history.append((now_ns, float(state_up["spot"])))
                if len(self.spot_history) > 240:
                    self.spot_history = self.spot_history[-180:]
                self._maybe_stamp_strike(float(state_up["spot"]))
                feats = build_market_features(
                    {
                        "spot": state_up["spot"],
                        "strike": self.strike or state_up["spot"],
                        "time_remaining_s": time_rem,
                        "bids": state_up["bids"],
                        "asks": state_up["asks"],
                    }
                )
                fair_up = estimate_fair_values(
                    feats, sigma_annual=float(self.cfg.get("sigma_annual", 0.55))
                )["up"]
                fair = (1.0 - fair_up) if self.position_leg == "down" else fair_up
                bb, ba = state["best_bid"], state["best_ask"]
                bb_up, ba_up = state_up["best_bid"], state_up["best_ask"]
                mid = (bb + ba) / 2 if bb is not None and ba is not None else None
                mid_up = (
                    (bb_up + ba_up) / 2
                    if bb_up is not None and ba_up is not None
                    else None
                )
                if mid_up is not None:
                    self.mid_history.append((now_ns, float(mid_up)))
                    if len(self.mid_history) > 240:
                        self.mid_history = self.mid_history[-180:]

                if mid is not None and abs(self.inventory_shares) > 1e-9:
                    await self._maybe_exit(
                        pos_id,
                        mid,
                        fair,
                        best_bid=bb,
                        best_ask=ba,
                        time_rem=time_rem,
                    )
                    await self._poll_fills(pos_id)

                quote = self._maker_quote(
                    fair_up,
                    bb_up,
                    ba_up,
                    state_up["spot"],
                    time_rem,
                    bids=state_up["bids"],
                    asks=state_up["asks"],
                )
                max_entries = int(self.cfg.get("max_entry_fills") or 2)
                cd = float(self.cfg.get("cooldown_after_fill_s") or 5)
                flat = abs(self.inventory_shares) < 1e-9
                now_m = time.monotonic()
                if self._session_loss_kill():
                    # Intentar flatten residual y salir del loop
                    if abs(self.inventory_shares) > 1e-9:
                        await self._force_flatten(
                            pos_id,
                            best_bid=bb,
                            best_ask=ba,
                            reason="kill",
                        )
                    break
                # Con inventario: no nuevas entradas; gestionar exit
                if not flat:
                    self._progress(minutes, "in_pos")
                    await asyncio.sleep(poll_s)
                    continue
                if self._halt_new_entries or self._dust_stuck:
                    self._progress(minutes, "halt_dust")
                    await asyncio.sleep(poll_s)
                    continue
                if quote is None:
                    self._progress(minutes, "wait_edge")
                    await asyncio.sleep(poll_s)
                    continue
                if max_entries > 0 and self._entry_fills >= max_entries:
                    self._progress(minutes, "max_entries")
                    await asyncio.sleep(poll_s)
                    continue
                if cd > 0 and self._last_fill_mono and (now_m - self._last_fill_mono) < cd:
                    self._progress(minutes, "cooldown")
                    await asyncio.sleep(poll_s)
                    continue

                snap = {
                    "spot": state_up["spot"],
                    "strike": self.strike or state_up["spot"],
                    "time_remaining_s": time_rem,
                    "best_bid": bb_up,
                    "best_ask": ba_up,
                    "inventory_shares": self.inventory_shares,
                    "mark_price": mid_up or fair_up,
                    "max_inventory_usdc": float(self.cfg.get("max_inventory_usdc") or 5),
                    "kill_switch_feed_stale_ms": float(self.cfg.get("kill_switch_feed_stale_ms") or 1800),
                    "feed_age_ms": 0,
                    "quote_bid": quote.bid,
                    "quote_ask": quote.ask,
                    "quote_size": quote.size_shares,
                    "fast_path_min_spread_cents": float(self.cfg.get("fast_path_min_spread_cents", 1.0)),
                    "edge_abs": abs(fair_up - mid_up) if mid_up is not None else None,
                    "min_edge": float(self.cfg.get("min_edge", 0.03)),
                }
                decision, _nim = decide_quote_action(snapshot=snap, latency_budget_ms=2500)
                self._decision_count += 1
                with (self.out_dir / "decisions.jsonl").open("a", encoding="utf-8") as dh:
                    dh.write(
                        json.dumps(
                            {
                                "ts_ms": int(time.time() * 1000),
                                "action": decision.action,
                                "reason": decision.reason,
                                "source": decision.source,
                                "live": True,
                                "dry_run": gates.dry_run,
                                "leg": (
                                    "up"
                                    if self._is_cheap_quote(quote)
                                    else "down"
                                    if self._is_rich_quote(quote)
                                    else "?"
                                ),
                            }
                        )
                        + "\n"
                    )

                if decision.action == "hold":
                    self._progress(minutes, "hold")
                    await asyncio.sleep(poll_s)
                    continue

                need_requote = (
                    self.open_order_id is None
                    or self.last_quote_spot is None
                    or abs(state_up["spot"] - self.last_quote_spot) >= requote_move
                    or decision.action == "cancel_replace"
                )
                if need_requote:
                    self.last_quote_spot = state_up["spot"]
                    tag = await self._post_entry(
                        target,
                        quote,
                        bb=bb_up,
                        ba=ba_up,
                        fair_up=fair_up,
                    )
                    self._progress(minutes, tag)
                else:
                    self._progress(minutes, "resting")
                await asyncio.sleep(poll_s)
        finally:
            # Liberar claim de desk
            try:
                from polymarket.research.local_lab.desk_coordinator import release

                if self.current_market_id:
                    release(line_id=self.desk_line_id, market_id=self.current_market_id)
            except Exception:
                pass
            # Último intento de flatten + sync fills
            try:
                if abs(self.inventory_shares) > 1e-9 and self.open_token_id:
                    st_f = await self._fetch_state(self.open_token_id)
                    if st_f:
                        await self._force_flatten(
                            self.open_token_id,
                            best_bid=st_f.get("best_bid"),
                            best_ask=st_f.get("best_ask"),
                            reason="session_end",
                        )
                        await asyncio.sleep(1.5)
                        await self._poll_fills(self.open_token_id)
            except Exception as e:
                print(f"END_FLATTEN_ERR {type(e).__name__}: {e}", flush=True)
            await self._cancel_open(reason="session_end")
            try:
                await asyncio.to_thread(self.clob.cancel_all)
            except Exception:
                pass

        # Mark residual a mid (si queda) para no mentir en PnL
        mark_adj = 0.0
        if abs(self.inventory_shares) > 1e-9 and self.open_token_id:
            st_m = await self._fetch_state(self.open_token_id)
            if st_m and st_m.get("best_bid") is not None and st_m.get("best_ask") is not None:
                mid_m = (float(st_m["best_bid"]) + float(st_m["best_ask"])) / 2.0
                avg = self.cost_basis / self.inventory_shares
                mark_adj = (mid_m - avg) * self.inventory_shares
        net = self.realized_pnl + mark_adj
        self.bankroll = float(self.cfg["initial_capital_usdc"]) + net
        if abs(self.inventory_shares) > 1e-9:
            print(
                f"WARN inventory residual={self.inventory_shares:.2f} "
                f"mark_adj={mark_adj:+.2f} (revisar Polymarket)",
                flush=True,
            )
        report = {
            "verdict": "LIVE_DRY_RUN" if gates.dry_run else "LIVE_ONCHAIN",
            "verdict_binding": not gates.dry_run,
            "demo_capital_usdc": float(self.cfg.get("initial_capital_usdc", 0)),
            "currency_label": "EUR",
            "demo_label": self.cfg.get("demo_label"),
            "strategy_id": self.strategy_id,
            "duration_minutes": minutes,
            "session_dir": str(self.out_dir),
            "fills": len(self.fills),
            "quotes_logged": self.quotes_logged,
            "bankroll_end_usdc": round(self.bankroll, 2),
            "net_session_usdc": round(net, 2),
            "realized_pnl_usdc": round(self.realized_pnl, 2),
            "dry_run": gates.dry_run,
            "armed": gates.armed,
            "inventory_residual": self.inventory_shares,
            "desk_line_id": self.desk_line_id,
            "desk_coord_mode": self._coord_mode(),
            "desk_role": self._desk_role(),
            "coord_blocks": self._coord_blocks,
        }
        (self.out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        with fills_path.open("w", encoding="utf-8") as fh:
            for f in self.fills:
                fh.write(json.dumps(f.__dict__) + "\n")
        print(f"  net={net:+.2f} fills={len(self.fills)}", flush=True)
        if not gates.dry_run:
            day = record_session_pnl(net)
            print(
                f"DAY_PNL pnl={day.get('pnl')} sessions={day.get('sessions')}",
                flush=True,
            )
        print("=== session 1/1 done ===", flush=True)
        return report


async def run_live_session(
    *,
    minutes: float,
    config_path: Path,
    session_id: str | None = None,
    strategy: str | None = None,
    desk_line_id: int = 1,
) -> dict[str, Any]:
    gates = read_gates()
    if not gates.armed:
        raise RuntimeError("POLY_LIVE_ARMED=0 — no se inicia live")
    cfg = load_maker_cfg(config_path)
    capital = float(cfg.get("initial_capital_usdc") or 0)
    # Paridad paper: pulse/fusion configs usan maker_fusion (no maker_edge).
    sid_strat = (
        strategy
        or cfg.get("strategy_id")
        or (
            "maker_fusion"
            if any(
                x in str(cfg.get("demo_label", "")).lower()
                for x in ("pulse", "fusion", "follow", "flow", "shadow", "promo")
            )
            else "maker_edge"
        )
    )
    if sid_strat not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {sid_strat}")
    clob = ClobLiveClient()
    clob.connect()
    # Dry + saldo virtual: no exigir capital ≤ balance real CLOB.
    if gates.dry_run and os.getenv("POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC"):
        try:
            virt = float(os.environ["POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC"])
            os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = str(
                max(float(os.getenv("POLY_LIVE_MAX_CAPITAL_USDC") or 0), capital, virt)
            )
        except ValueError:
            pass
    clob.assert_can_trade(capital=capital, allow_dry=True)
    sid = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = OUT_BASE / "live_maker" / f"session_{sid}"
    print(
        f"LIVE_STRAT={sid_strat} label={cfg.get('demo_label')} capital={capital} "
        f"line={desk_line_id} coord={cfg.get('desk_coord_mode') or os.getenv('POLY_DESK_COORD_MODE')}",
        flush=True,
    )
    session = LiveSession(
        cfg=cfg,
        out_dir=out,
        clob=clob,
        bankroll=capital,
        strategy_id=str(sid_strat),
        desk_line_id=int(desk_line_id),
    )
    return await session.run(minutes=minutes)


def main() -> int:
    p = argparse.ArgumentParser(description="Live maker post-only (gated)")
    p.add_argument("--config", required=True)
    p.add_argument("--minutes", type=float, default=5.0)
    p.add_argument("--session-id", default=None)
    p.add_argument(
        "--strategy",
        default=None,
        help="Override strategy (default: cfg/demo_label → maker_fusion for pulse)",
    )
    args = p.parse_args()
    path = Path(args.config)
    if not path.is_file():
        path = ROOT.parent / args.config
    report = asyncio.run(
        run_live_session(
            minutes=args.minutes,
            config_path=path,
            session_id=args.session_id,
            strategy=args.strategy,
        )
    )
    print(
        json.dumps(
            {
                "ok": True,
                "net": report.get("net_session_usdc"),
                "fills": report.get("fills"),
                "strategy_id": report.get("strategy_id"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
