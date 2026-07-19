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
from polymarket.research.local_lab.strategies import STRATEGIES, apply_inventory_skew
from polymarket.src.ai.decision_engine import decide_quote_action
from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.data.book_utils import best_bid_ask
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
    window_end_ns: int | None = None
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
    _cash_bal: float | None = None
    _cash_bal_mono: float = 0.0
    _skip_cash_until: float = 0.0

    def _maker_quote(self, fair: float, bb: float | None, ba: float | None, spot: float, time_rem: float):
        self.cfg["_time_remaining_s"] = time_rem
        self.cfg["_runtime_size_scale"] = 1.0
        fn = STRATEGIES["maker_edge"]
        raw = fn(fair, bb, ba, spot, self.strike or spot, self.cfg)
        if raw is None:
            return None
        return apply_inventory_skew(raw, inventory_shares=self.inventory_shares, cfg=self.cfg)

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
        if side_u == "BUY" and not self.clob.gates.dry_run:
            # CLOB real: notional BUY <= collateral libre (pUSD).
            # En DRY_RUN no bloqueamos por balance (no hay gasto real).
            now_m = time.monotonic()
            if now_m < self._skip_cash_until:
                return
            cash = await self._refresh_cash(force=False)
            need = px * sz
            # Buffer 2¢ por redondeos CLOB
            if need > cash - 0.02:
                # Con min 5 shares solo cabe si px <= (cash-0.02)/5
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
        sz = max(float(quote.size_shares), MIN_ORDER_SHARES)
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
        lock = float(self.cfg.get("lock_profit_usdc") or 0.15)
        # Live micro: take profit / cut loss más agresivo que paper 100€
        lock = min(lock, 0.20)
        max_loss = min(float(self.cfg.get("max_loss_usdc") or 0.5), 0.35)
        avg = self.cost_basis / self.inventory_shares
        unreal = self.inventory_shares * mid - self.cost_basis
        flatten_s = float(self.cfg.get("flatten_before_window_s") or 45)
        urgent = time_rem <= flatten_s
        take = unreal >= lock
        stop = unreal <= -max_loss
        fade = fair < avg - 0.015
        # Tras fill de entrada: empezar a salir en cuanto haya +1 tick o urgencia
        quick = unreal >= 0.05 or (self._entry_fills > 0 and unreal >= 0.02 and time_rem < 120)
        if urgent or take or stop or fade or quick:
            if self.open_side == "SELL" and self.open_order_id and not urgent:
                return  # ya hay exit resting
            await self._force_flatten(
                token_id, best_bid=best_bid, best_ask=best_ask, reason=
                "urgent" if urgent else "tp" if take else "sl" if stop else "fade" if fade else "quick"
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

                # Dry: una prueba de sizing (size 1 → floor 5). Live real: solo log.
                if not smoke_done:
                    smoke_done = True
                    state0 = await self._fetch_state(target.token_id_up)
                    bb0 = state0["best_bid"] if state0 else 0.40
                    ba0 = state0["best_ask"] if state0 else 0.60
                    # Precio de prueba en banda media (evita bid 0.95 * 5 = notional enorme)
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
                    if gates.dry_run:
                        # Dejar resting: _poll_fills simulará DRY_FILL a ~2s y luego exit
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
                    we = window_end(target)
                    self.window_end_ns = int(we.timestamp() * 1e9) if we else None
                    async with httpx.AsyncClient(timeout=12.0) as c:
                        self.strike, _src = await fetch_btc_spot_async(c)
                    self.last_quote_spot = None
                    print(f"MARKET {target.question[:80]}", flush=True)

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
                    fair_up, bb_up, ba_up, state_up["spot"], time_rem
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
            "strategy_id": "maker_edge",
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
) -> dict[str, Any]:
    gates = read_gates()
    if not gates.armed:
        raise RuntimeError("POLY_LIVE_ARMED=0 — no se inicia live")
    cfg = load_maker_cfg(config_path)
    capital = float(cfg.get("initial_capital_usdc") or 0)
    clob = ClobLiveClient()
    clob.connect()
    clob.assert_can_trade(capital=capital, allow_dry=True)
    sid = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = OUT_BASE / "live_maker" / f"session_{sid}"
    session = LiveSession(
        cfg=cfg,
        out_dir=out,
        clob=clob,
        bankroll=capital,
    )
    return await session.run(minutes=minutes)


def main() -> int:
    p = argparse.ArgumentParser(description="Live maker post-only (gated)")
    p.add_argument("--config", required=True)
    p.add_argument("--minutes", type=float, default=5.0)
    p.add_argument("--session-id", default=None)
    args = p.parse_args()
    path = Path(args.config)
    if not path.is_file():
        path = ROOT.parent / args.config
    report = asyncio.run(
        run_live_session(minutes=args.minutes, config_path=path, session_id=args.session_id)
    )
    print(json.dumps({"ok": True, "net": report.get("net_session_usdc"), "fills": report.get("fills")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
