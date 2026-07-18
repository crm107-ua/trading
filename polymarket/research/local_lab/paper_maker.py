#!/usr/bin/env python3
"""
Paper maker local — simula cotizaciones y fills sin on-chain.

Salida: polymarket/data_local/local_lab/<strategy>/session_<id>/
NO es screen fase B/C. NO proyectar ingresos anuales desde aquí.
"""

from __future__ import annotations

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
from polymarket.research.local_lab.strategies import STRATEGIES, QuoteIntent
from polymarket.src.data.book_utils import best_bid_ask
from polymarket.src.data.btc_spot import fetch_btc_spot_async
from polymarket.src.pricing.fair_value import estimate_fair_values
from polymarket.src.signals.features import build_market_features
from polymarket.src.ai.decision_engine import (
    Decision,
    decide_inventory_exit,
    decide_quote_action,
    grind_mode_enabled,
    profit_assist_enabled,
)
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

ROOT = Path(__file__).resolve().parents[2]
MAKER_CFG = ROOT / "config" / "maker.json"
OUT_BASE = ROOT / "data_local" / "local_lab"


@dataclass
class VirtualFill:
    ts_ns: int
    side: str
    price: float
    size: float
    fair: float
    spot: float
    market_id: str
    question: str
    spread_captured: float
    adverse: bool


@dataclass
class PaperSession:
    strategy_id: str
    cfg: dict[str, Any]
    out_dir: Path
    bankroll: float
    inventory_shares: float = 0.0
    cost_basis: float = 0.0
    spread_total: float = 0.0
    adverse_total: float = 0.0
    fills: list[VirtualFill] = field(default_factory=list)
    quotes_logged: int = 0
    last_quote_spot: float | None = None
    last_trade_seen: float | None = None
    current_market_id: str | None = None
    current_question: str | None = None
    strike: float | None = None
    window_end_ns: int | None = None
    spot_history: list[tuple[int, float]] = field(default_factory=list)
    nim_decisions_used: int = 0
    nim_rule_holds: int = 0
    nim_cache_hits: int = 0
    last_nim_latency_ms: int | None = None
    _decision_count: int = 0
    _last_progress_log: float = 0.0
    _session_start_mono: float = 0.0
    _touch_posts: int = 0
    _last_fill_mono: float = 0.0
    _entry_fills: int = 0
    _size_scale: float = 1.0
    _size_scale_until: float = 0.0
    _consecutive_round_losses: int = 0
    _entries_paused_until: float = 0.0
    _session_entries_killed: bool = False
    _last_exit_nim_mono: float = 0.0

    def _strategy_fn(self):
        fn = STRATEGIES[self.strategy_id]
        if self.strategy_id == "maker_16":
            return lambda fair, bb, ba, spot, strike: fn(fair, self.cfg, bb, ba)
        return lambda fair, bb, ba, spot, strike: fn(fair, bb, ba, spot, strike, self.cfg)

    def _maker_quotes(
        self,
        fair: float,
        bb: float | None,
        ba: float | None,
        spot: float,
        *,
        time_remaining_s: float | None = None,
    ) -> QuoteIntent | None:
        from polymarket.research.local_lab.strategies import apply_inventory_skew

        if time_remaining_s is not None:
            self.cfg["_time_remaining_s"] = time_remaining_s
        now = time.monotonic()
        if now >= self._size_scale_until:
            self._size_scale = 1.0
        self.cfg["_runtime_size_scale"] = self._size_scale
        raw = self._strategy_fn()(fair, bb, ba, spot, self.strike or spot)
        if raw is None:
            return None
        min_mkt = float(self.cfg.get("min_market_spread", 0.0))
        if min_mkt > 0 and bb is not None and ba is not None and (ba - bb) < min_mkt:
            return None
        mid = (bb + ba) / 2.0 if bb is not None and ba is not None else None
        return apply_inventory_skew(
            raw, inventory_shares=self.inventory_shares, cfg=self.cfg, mid=mid
        )

    def _resolve_window(self, resolved_up: int) -> float:
        if abs(self.inventory_shares) < 1e-9:
            return 0.0
        mode = str(self.cfg.get("paper_resolution", "binary")).lower()
        if mode == "mid":
            return 0.0
        payout = self.inventory_shares * resolved_up
        pnl = payout - self.cost_basis
        self.bankroll += payout
        self.inventory_shares = 0.0
        self.cost_basis = 0.0
        self._on_round_closed(pnl)
        return pnl

    def _session_net(self) -> float:
        return self.bankroll - float(self.cfg["initial_capital_usdc"])

    def _equity_net(self, mid: float | None = None) -> float:
        """PnL de sesión mark-to-mid (incluye inventario abierto)."""
        if mid is not None and abs(self.inventory_shares) > 1e-9:
            return (
                self.bankroll
                + self.inventory_shares * mid
                - float(self.cfg["initial_capital_usdc"])
            )
        return self._session_net()

    def _trip_session_kill(self, mid: float | None = None) -> bool:
        """Si el equity cae bajo el kill: flatten + bloquear nuevas entradas."""
        kill = float(self.cfg.get("session_kill_net_usdc", 0) or 0)
        if kill <= 0 or self._session_entries_killed:
            return self._session_entries_killed
        if self._equity_net(mid) > -abs(kill):
            return False
        self._session_entries_killed = True
        if mid is not None and abs(self.inventory_shares) > 1e-9:
            self._flatten_inventory_mid(mid)
        return True

    def _on_round_closed(self, pnl: float) -> None:
        """Anti-racha + kill-switch tras cerrar inventario."""
        now = time.monotonic()
        if pnl < -1e-9:
            self._consecutive_round_losses += 1
            pen = float(self.cfg.get("loss_size_penalty", 0.5))
            hold = float(self.cfg.get("loss_size_penalty_s", 120) or 120)
            self._size_scale = max(0.25, min(1.0, pen))
            self._size_scale_until = now + hold
            max_streak = int(self.cfg.get("pause_after_consecutive_losses", 2) or 0)
            if max_streak > 0 and self._consecutive_round_losses >= max_streak:
                pause_s = float(self.cfg.get("pause_entries_s", 300) or 300)
                self._entries_paused_until = now + pause_s
        else:
            self._consecutive_round_losses = 0
            if now >= self._size_scale_until:
                self._size_scale = 1.0
        self._trip_session_kill(None)

    def _flatten_inventory_mid(self, mark: float) -> float:
        """Mark-to-mid exit — maker no debería llevar inventario a resolución binaria."""
        if abs(self.inventory_shares) < 1e-9:
            return 0.0
        mark = max(0.01, min(0.99, mark))
        notional = self.inventory_shares * mark
        pnl = notional - self.cost_basis
        self.bankroll += notional
        self.inventory_shares = 0.0
        self.cost_basis = 0.0
        self._on_round_closed(pnl)
        return pnl

    def _dynamic_tp(self, fair: float, avg: float) -> float:
        """Capture a large fraction of remaining edge; floor/ceiling from config."""
        base = float(self.cfg.get("min_take_profit", 0.01))
        scale = float(self.cfg.get("tp_edge_scale", 0.5))
        cap = float(self.cfg.get("max_take_profit", 0.06))
        frac = float(self.cfg.get("tp_capture_frac", 0.55))
        edge_now = abs(fair - avg)
        target = max(base, frac * edge_now, base + scale * max(0.0, edge_now - base))
        return max(base, min(cap, target))

    def _manage_inventory_exits(
        self,
        mid: float,
        fair: float,
        *,
        exit_mark: float | None = None,
    ) -> None:
        if abs(self.inventory_shares) < 1e-9:
            return
        # Session kill on mark-to-mid equity — para YA (flatten + no más entries).
        if self._trip_session_kill(mid):
            return
        avg = self.cost_basis / self.inventory_shares
        tp = self._dynamic_tp(fair, avg)
        stop = float(self.cfg.get("stop_loss_mid", 0.0) or 0.0)
        # Conservative mark for stops: bid if long, ask if short (exitable price).
        mark = mid if exit_mark is None else float(exit_mark)
        if self.cfg.get("take_profit_mid", True):
            if self.inventory_shares > 0 and mid >= avg + tp:
                self._flatten_inventory_mid(mid)
                return
            if self.inventory_shares < 0 and mid <= avg - tp:
                self._flatten_inventory_mid(mid)
                return
        # Early exit if fair no longer favors the position (cut red faster).
        if self.cfg.get("fair_fade_exit", False):
            if self.inventory_shares > 0 and fair < mid - 1e-9 and mid < avg:
                self._flatten_inventory_mid(mid)
                return
            if self.inventory_shares < 0 and fair > mid + 1e-9 and mid > avg:
                self._flatten_inventory_mid(mid)
                return
        # Corte por PnL no realizado usando precio ejecutable (no mid optimista).
        unreal = self.inventory_shares * mark - self.cost_basis
        max_loss = float(self.cfg.get("max_loss_usdc", 0) or 0)
        if max_loss > 0:
            grindish = (
                grind_mode_enabled()
                or bool(self.cfg.get("preserve_selectivity"))
                or "grind" in str(self.cfg.get("demo_label", "")).lower()
            )
            soft = abs(max_loss) * (0.7 if grindish else 1.0)
            if unreal <= -soft:
                self._flatten_inventory_mid(mark)
                return
        if stop > 0:
            if max_loss > 0 and abs(self.inventory_shares) > 1e-9:
                stop = min(stop, max_loss / abs(self.inventory_shares))
            if self.inventory_shares > 0 and mark <= avg - stop:
                self._flatten_inventory_mid(mark)
            elif self.inventory_shares < 0 and mark >= avg + stop:
                self._flatten_inventory_mid(mark)

    def _smart_flatten(self, mid: float, fair: float) -> float:
        """
        Exit ladder (honest paper):
        1) mid already locks take-profit → exit mid
        2) else mark-to-mid (no synthetic TP / fair exits)
        """
        if abs(self.inventory_shares) < 1e-9:
            return 0.0
        avg = self.cost_basis / self.inventory_shares
        min_tp = float(self.cfg.get("min_take_profit", 0.01))
        if self.inventory_shares > 0 and mid >= avg + min_tp:
            return self._flatten_inventory_mid(mid)
        if self.inventory_shares < 0 and mid <= avg - min_tp:
            return self._flatten_inventory_mid(mid)
        return self._flatten_inventory_mid(mid)

    def _maybe_hazard_tp_exit(self, mid: float | None, fair: float, dt_s: float = 1.0) -> None:
        """Exit at mid only when mid already locks take-profit (no synthetic TP fills)."""
        if mid is None or abs(self.inventory_shares) < 1e-9:
            return
        if not self.cfg.get("exit_hazard_per_s"):
            return
        # Keep flag for config compat, but only act when mid is already at TP.
        min_tp = float(self.cfg.get("min_take_profit", 0.01))
        avg = self.cost_basis / self.inventory_shares
        if self.inventory_shares > 0 and mid >= avg + min_tp:
            self._flatten_inventory_mid(mid)
        elif self.inventory_shares < 0 and mid <= avg - min_tp:
            self._flatten_inventory_mid(mid)

    def _check_fill(
        self,
        last_trade: float | None,
        quote: QuoteIntent,
        fair: float,
        spot: float,
        best_bid: float | None = None,
        best_ask: float | None = None,
    ) -> None:
        """Fill only on a *new* last_trade that actually hits our resting quote."""
        if last_trade is None:
            return
        if self.last_trade_seen is not None and abs(last_trade - self.last_trade_seen) < 1e-9:
            return
        self.last_trade_seen = last_trade

        side = None
        price = None
        # Correct maker hit: trade through our bid / ask (not "near mid")
        if quote.bid > 0.02 and last_trade <= quote.bid + 1e-9:
            side, price = "bid", quote.bid
        elif quote.ask < 0.98 and last_trade >= quote.ask - 1e-9:
            side, price = "ask", quote.ask
        if side is None:
            return

        mid = None
        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2.0
        toxic_tol = float(self.cfg.get("toxic_tol", 0.01))
        # Reject immediately toxic fills vs mid (paper approximation of cancel-before-hit)
        if mid is not None:
            if side == "bid" and mid < price - toxic_tol:
                return
            if side == "ask" and mid > price + toxic_tol:
                return
        # Edge filter: only buy if fair still above mid; only sell if fair below mid
        min_edge = float(self.cfg.get("min_edge", 0.0))
        if min_edge > 0 and mid is not None:
            if side == "bid" and fair - mid < min_edge * 0.5:
                return
            if side == "ask" and mid - fair < min_edge * 0.5:
                return

        notional = price * quote.size_shares
        if notional > float(self.cfg["max_notional_per_side_usdc"]):
            return
        inv_usd = abs(self.inventory_shares * price)
        if inv_usd + notional > float(self.cfg["max_inventory_usdc"]):
            return

        spread_cap = (float(self.cfg["half_spread"]) + float(self.cfg["safety_buffer"])) * quote.size_shares
        ts_ns = time.time_ns()
        self.spot_history.append((ts_ns, spot))
        adverse = False
        adv_usd = float(self.cfg["adverse_selection_spot_move_usd"])
        win_ms = int(self.cfg["adverse_selection_window_ms"])
        for t, s in reversed(self.spot_history):
            if ts_ns - t > win_ms * 1_000_000:
                break
            if side == "bid" and s < spot - adv_usd:
                adverse = True
            if side == "ask" and s > spot + adv_usd:
                adverse = True
        if adverse and self.cfg.get("reject_adverse_fills", True):
            return
        # No piramidar: v6 perdió apilando 2–3 bids en la misma dirección.
        if self.cfg.get("no_pyramid_entries", True) and abs(self.inventory_shares) > 1e-9:
            increasing = (side == "bid" and self.inventory_shares > 0) or (
                side == "ask" and self.inventory_shares < 0
            )
            if increasing:
                return
        self.spread_total += spread_cap
        self.adverse_total += spread_cap if adverse else 0.0
        inv_before = self.inventory_shares
        if side == "bid":
            self.inventory_shares += quote.size_shares
            self.cost_basis += notional
            self.bankroll -= notional
        else:
            self.inventory_shares -= quote.size_shares
            self.cost_basis -= notional
            self.bankroll += notional
        self.fills.append(
            VirtualFill(
                ts_ns=ts_ns,
                side=side,
                price=price,
                size=quote.size_shares,
                fair=fair,
                spot=spot,
                market_id=self.current_market_id or "",
                question=self.current_question or "",
                spread_captured=spread_cap,
                adverse=adverse,
            )
        )
        self._last_fill_mono = time.monotonic()
        # Entry = fill that increases absolute inventory risk.
        if abs(self.inventory_shares) > abs(inv_before) + 1e-9:
            self._entry_fills += 1
        self._maybe_lock_spread_exit(fair, best_bid, best_ask)
        if mid is not None and abs(self.inventory_shares) > 1e-9:
            self._manage_inventory_exits(mid, fair)

    def _maybe_lock_spread_exit(
        self, fair: float, best_bid: float | None, best_ask: float | None
    ) -> None:
        mode = str(self.cfg.get("paper_pnl_mode", "")).lower()
        if mode == "locked_spread":
            # Explicit synthetic mode only — never use for honest selection metrics.
            self._flatten_inventory_mid(fair)
        elif self.cfg.get("flatten_after_fill", False) and best_bid is not None and best_ask is not None:
            # Honest MTM: always mark at observable mid (never invent fair as exit).
            mid = (best_bid + best_ask) / 2.0
            self._flatten_inventory_mid(mid)

    def _maybe_paper_touch_fill(
        self,
        quote: QuoteIntent,
        fair: float,
        spot: float,
        best_bid: float | None,
        best_ask: float | None,
    ) -> None:
        """
        Paper-only: when quoting at touch, inject a fill every N posts.
        Needed because CLOB REST last_trade rarely updates in short sessions.
        """
        n = int(self.cfg.get("paper_touch_fill_every_n", 0) or 0)
        if n <= 0 or best_bid is None or best_ask is None:
            return
        at_bid = quote.bid > 0.02 and abs(quote.bid - best_bid) <= 1e-9
        at_ask = quote.ask < 0.98 and abs(quote.ask - best_ask) <= 1e-9
        if not (at_bid or at_ask):
            return
        self._touch_posts += 1
        if self._touch_posts % n != 0:
            return
        # Alternate sides; prefer reducing inventory when skewed
        if self.inventory_shares > 1e-9 and at_ask:
            side, price = "ask", quote.ask
        elif self.inventory_shares < -1e-9 and at_bid:
            side, price = "bid", quote.bid
        elif at_bid and (self._touch_posts // n) % 2 == 1:
            side, price = "bid", quote.bid
        elif at_ask:
            side, price = "ask", quote.ask
        elif at_bid:
            side, price = "bid", quote.bid
        else:
            return
        # Re-use fill path via synthetic last_trade
        prev = self.last_trade_seen
        self.last_trade_seen = None  # force accept
        self._check_fill(price, quote, fair, spot, best_bid=best_bid, best_ask=best_ask)
        if self.last_trade_seen is None:
            self.last_trade_seen = prev

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
        lt = book.get("last_trade_price") or book.get("lastTradePrice")
        return {
            "spot": spot,
            "bids": bids,
            "asks": asks,
            "best_bid": bb,
            "best_ask": ba,
            "last_trade": float(lt) if lt is not None else None,
            "feed_ts_ms": int(time.time() * 1000),
        }

    def _log_progress(self, minutes: float, decision: Decision) -> None:
        now = time.monotonic()
        if now - self._last_progress_log < 10.0 and self._decision_count % 5 != 0:
            return
        self._last_progress_log = now
        elapsed_min = (now - self._session_start_mono) / 60.0
        pct = min(99.9, round(100.0 * elapsed_min / minutes, 1)) if minutes > 0 else 0.0
        print(
            f"paper {pct}% [{elapsed_min:.1f}/{minutes:.1f} min] "
            f"decisions={self._decision_count} quotes={self.quotes_logged} fills={len(self.fills)} "
            f"last={decision.action} ({decision.source})",
            flush=True,
        )

    async def run(self, minutes: float = 30.0) -> dict[str, Any]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._session_start_mono = time.monotonic()
        print(f"Paper OUT: {self.out_dir}", flush=True)
        print(f"Progreso cada ~10s. O en otra terminal: python scripts/trading_progress.py --watch 10", flush=True)
        fills_path = self.out_dir / "fills.jsonl"
        end_at = time.monotonic() + minutes * 60
        poll_s = 1.0
        requote_move = float(self.cfg["requote_spot_move_usd"])
        prev_market: str | None = None

        while time.monotonic() < end_at:
            markets = await asyncio.to_thread(discover_btc_5m_updown)
            now = datetime.now(timezone.utc)
            active, nxt = pick_recording_targets(markets, now)
            target = active or nxt
            if target is None:
                await asyncio.sleep(poll_s)
                continue

            if target.market_id != self.current_market_id:
                if prev_market and self.strike is not None and self.window_end_ns:
                    state = await self._fetch_state(target.token_id_up)
                    if state:
                        bb, ba = state["best_bid"], state["best_ask"]
                        if str(self.cfg.get("paper_resolution", "binary")).lower() == "mid" and bb is not None and ba is not None:
                            mid_x = (bb + ba) / 2
                            self._smart_flatten(mid_x, mid_x)
                        else:
                            resolved = int(state["spot"] > self.strike)
                            self._resolve_window(resolved)
                prev_market = target.market_id
                self.current_market_id = target.market_id
                self.current_question = target.question
                ws = window_start(target)
                we = window_end(target)
                self.window_end_ns = int(we.timestamp() * 1e9) if we else None
                async with httpx.AsyncClient(timeout=12.0) as c:
                    self.strike, _src = await fetch_btc_spot_async(c)
                self.last_trade_seen = None
                self.last_quote_spot = None

            state = await self._fetch_state(target.token_id_up)
            if state is None:
                await asyncio.sleep(poll_s)
                continue

            we_ns = self.window_end_ns or time.time_ns()
            time_rem = max((we_ns - time.time_ns()) / 1e9, 1.0)
            feats = build_market_features(
                {
                    "spot": state["spot"],
                    "strike": self.strike or state["spot"],
                    "time_remaining_s": time_rem,
                    "bids": state["bids"],
                    "asks": state["asks"],
                }
            )
            fair = estimate_fair_values(
                feats, sigma_annual=float(self.cfg.get("sigma_annual", 0.55))
            )["up"]
            if self.last_quote_spot is None or abs(state["spot"] - self.last_quote_spot) >= requote_move:
                self.last_quote_spot = state["spot"]
            # Manage open inventory every tick BEFORE window flatten (stops first).
            if (
                abs(self.inventory_shares) > 1e-9
                and state["best_bid"] is not None
                and state["best_ask"] is not None
            ):
                mid_m = (state["best_bid"] + state["best_ask"]) / 2.0
                exit_mark = (
                    float(state["best_bid"])
                    if self.inventory_shares > 0
                    else float(state["best_ask"])
                )
                self._manage_inventory_exits(mid_m, fair, exit_mark=exit_mark)
                # NIM profit-assist: ¿dejar correr TP o flatten ya?
                if (
                    profit_assist_enabled() or grind_mode_enabled()
                ) and abs(self.inventory_shares) > 1e-9:
                    every = float(os.environ.get("NVIDIA_NIM_EXIT_EVERY_S", "8") or 8)
                    now_e = time.monotonic()
                    if now_e - self._last_exit_nim_mono >= every:
                        self._last_exit_nim_mono = now_e
                        avg_e = self.cost_basis / self.inventory_shares
                        # PnL al precio ejecutable (bid long / ask short) — WR-lock
                        unreal = self.inventory_shares * exit_mark - self.cost_basis
                        exit_dec, exit_nim = decide_inventory_exit(
                            snapshot={
                                "inventory_shares": self.inventory_shares,
                                "avg_entry": avg_e,
                                "mark_price": exit_mark,
                                "fair_up": fair,
                                "unrealized_pnl_usdc": round(unreal, 4),
                                "time_remaining_s": time_rem,
                                "spot": state["spot"],
                                "best_bid": state["best_bid"],
                                "best_ask": state["best_ask"],
                                "lock_profit_usdc": float(
                                    self.cfg.get("lock_profit_usdc", 1.25) or 1.25
                                ),
                                "max_loss_usdc": float(
                                    self.cfg.get("max_loss_usdc", 0) or 0
                                ),
                                "grind_bank_usdc": float(
                                    self.cfg.get("grind_bank_usdc", 0.055) or 0.055
                                ),
                            },
                            latency_budget_ms=2500,
                        )
                        if exit_nim is not None:
                            self.nim_decisions_used += 1
                            self.last_nim_latency_ms = exit_nim.latency_ms
                            if exit_nim.cache_hit:
                                self.nim_cache_hits += 1
                        with (self.out_dir / "decisions.jsonl").open("a", encoding="utf-8") as dh:
                            dh.write(
                                json.dumps(
                                    {
                                        "ts_ms": int(time.time() * 1000),
                                        "market_id": self.current_market_id,
                                        "action": exit_dec.action,
                                        "reason": exit_dec.reason,
                                        "confidence": exit_dec.confidence,
                                        "source": exit_dec.source,
                                        "kind": "inventory_exit",
                                        "nim_model": exit_nim.model if exit_nim else None,
                                        "nim_latency_ms": exit_nim.latency_ms if exit_nim else None,
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                        if exit_dec.action == "flatten":
                            self._flatten_inventory_mid(mid_m)
            # Window flatten only if stops/NIM did not already cut.
            flatten_s = float(self.cfg.get("flatten_before_window_s", 0))
            if (
                flatten_s > 0
                and time_rem <= flatten_s
                and abs(self.inventory_shares) > 1e-9
                and state["best_bid"] is not None
                and state["best_ask"] is not None
            ):
                self._smart_flatten((state["best_bid"] + state["best_ask"]) / 2, fair)
            # Holding inventory: skip entry NIM/quotes (latency) so stops re-check every poll.
            if abs(self.inventory_shares) > 1e-9:
                await asyncio.sleep(poll_s)
                continue
            quote = self._maker_quotes(
                fair,
                state["best_bid"],
                state["best_ask"],
                state["spot"],
                time_remaining_s=time_rem,
            )
            # Risk gates for NEW entries only (inventory skew still exits).
            cd = float(self.cfg.get("cooldown_after_fill_s", 0) or 0)
            max_entries = int(self.cfg.get("max_entry_fills", 0) or 0)
            flat = abs(self.inventory_shares) < 1e-9
            now_m = time.monotonic()
            if quote is not None and flat:
                if self._session_entries_killed or now_m < self._entries_paused_until:
                    quote = None
                elif cd > 0 and self._last_fill_mono and (now_m - self._last_fill_mono) < cd:
                    quote = None
                elif max_entries > 0 and self._entry_fills >= max_entries:
                    quote = None
                else:
                    if self._trip_session_kill(
                        (state["best_bid"] + state["best_ask"]) / 2.0
                        if state.get("best_bid") is not None and state.get("best_ask") is not None
                        else None
                    ):
                        quote = None
            if quote is None:
                # Heartbeat aunque no haya edge (si no, parece colgado con edge alto)
                now_hb = time.monotonic()
                if now_hb - self._last_progress_log >= 10.0:
                    self._last_progress_log = now_hb
                    elapsed_min = (now_hb - self._session_start_mono) / 60.0
                    pct = min(99.9, round(100.0 * elapsed_min / minutes, 1)) if minutes > 0 else 0.0
                    mid_hb = None
                    edge_hb = None
                    why = "wait_edge"
                    if state.get("best_bid") is not None and state.get("best_ask") is not None:
                        mid_hb = (float(state["best_bid"]) + float(state["best_ask"])) / 2.0
                        edge_hb = abs(float(fair) - mid_hb)
                        mid_lo = float(self.cfg.get("min_quote_mid", 0) or 0)
                        mid_hi = float(self.cfg.get("max_quote_mid", 1) or 1)
                        need = float(self.cfg.get("min_edge", 0.03) or 0.03)
                        if mid_lo > 0 and mid_hb < mid_lo:
                            why = "wait_mid_lo"
                        elif mid_hi < 1 and mid_hb > mid_hi:
                            why = "wait_mid_hi"  # cola/lotería (p.ej. mid 0.93)
                        elif edge_hb is not None and edge_hb < need:
                            why = "wait_edge"
                        else:
                            why = "wait_filter"  # z / EV / time / spread
                    print(
                        f"paper {pct}% [{elapsed_min:.1f}/{minutes:.1f} min] "
                        f"decisions={self._decision_count} quotes={self.quotes_logged} "
                        f"fills={len(self.fills)} last={why} (rule) "
                        f"edge={edge_hb if edge_hb is not None else 'n/a'} "
                        f"need>={self.cfg.get('min_edge')} mid={mid_hb if mid_hb is not None else 'n/a'}",
                        flush=True,
                    )
                await asyncio.sleep(poll_s)
                continue

            now_ms = int(time.time() * 1000)
            feed_ts_ms = int(state.get("feed_ts_ms", now_ms))
            feed_age_ms = now_ms - feed_ts_ms

            snap = {
                "spot": state["spot"],
                "strike": self.strike or state["spot"],
                "time_remaining_s": time_rem,
                "best_bid": state["best_bid"],
                "best_ask": state["best_ask"],
                "last_trade": state["last_trade"],
                "last_quote_spot": self.last_quote_spot,
                "requote_spot_move_usd": requote_move,
                "inventory_shares": self.inventory_shares,
                "mark_price": (
                    (state["best_bid"] + state["best_ask"]) / 2
                    if state["best_bid"] is not None and state["best_ask"] is not None
                    else fair
                ),
                "max_inventory_usdc": float(self.cfg["max_inventory_usdc"]),
                "kill_switch_feed_stale_ms": float(self.cfg["kill_switch_feed_stale_ms"]),
                "feed_age_ms": feed_age_ms,
                "quote_bid": quote.bid,
                "quote_ask": quote.ask,
                "quote_size": quote.size_shares,
                "fast_path_min_spread_cents": float(self.cfg.get("fast_path_min_spread_cents", 1.0)),
                "edge_abs": abs(fair - ((state["best_bid"] + state["best_ask"]) / 2)) if state["best_bid"] is not None and state["best_ask"] is not None else None,
                "min_edge": float(self.cfg.get("min_edge", 0.03)),
            }
            decision, nim = decide_quote_action(snapshot=snap, latency_budget_ms=3000)
            self._decision_count += 1
            self._log_progress(minutes, decision)
            if nim is not None:
                self.nim_decisions_used += 1
                self.last_nim_latency_ms = nim.latency_ms
                if nim.cache_hit:
                    self.nim_cache_hits += 1
            elif decision.source == "rule":
                self.nim_rule_holds += 1

            decisions_path = self.out_dir / "decisions.jsonl"
            with decisions_path.open("a", encoding="utf-8") as dh:
                dh.write(
                    json.dumps(
                        {
                            "ts_ms": now_ms,
                            "market_id": self.current_market_id,
                            "action": decision.action,
                            "reason": decision.reason,
                            "confidence": decision.confidence,
                            "source": decision.source,
                            "nim_model": nim.model if nim else None,
                            "nim_latency_ms": nim.latency_ms if nim else None,
                            "nim_cache_hit": nim.cache_hit if nim else False,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

            if decision.action == "hold":
                await asyncio.sleep(poll_s)
                continue
            if decision.action == "cancel_replace":
                self.last_quote_spot = state["spot"]
            self.quotes_logged += 1
            fills_before = len(self.fills)
            self._check_fill(
                state["last_trade"],
                quote,
                fair,
                state["spot"],
                best_bid=state["best_bid"],
                best_ask=state["best_ask"],
            )
            self._maybe_paper_touch_fill(
                quote,
                fair,
                state["spot"],
                state["best_bid"],
                state["best_ask"],
            )
            if state["best_bid"] is not None and state["best_ask"] is not None:
                mid_now = (state["best_bid"] + state["best_ask"]) / 2
                self._maybe_hazard_tp_exit(mid_now, fair, dt_s=poll_s)
                # Immediate stop check on the fill tick (don't wait another poll).
                if len(self.fills) > fills_before and abs(self.inventory_shares) > 1e-9:
                    exit_mark = (
                        float(state["best_bid"])
                        if self.inventory_shares > 0
                        else float(state["best_ask"])
                    )
                    self._manage_inventory_exits(mid_now, fair, exit_mark=exit_mark)
            await asyncio.sleep(poll_s)

        # Resolve open inventory at session end
        if abs(self.inventory_shares) > 1e-9 and self.strike is not None:
            markets = await asyncio.to_thread(discover_btc_5m_updown)
            active, nxt = pick_recording_targets(markets, datetime.now(timezone.utc))
            target = active or nxt
            if target:
                state = await self._fetch_state(target.token_id_up)
                if state:
                    if (
                        str(self.cfg.get("paper_resolution", "binary")).lower() == "mid"
                        and state["best_bid"] is not None
                        and state["best_ask"] is not None
                    ):
                        mid_e = (state["best_bid"] + state["best_ask"]) / 2
                        # session-end: use mid as fair proxy if no fresh fair
                        self._smart_flatten(mid_e, mid_e)
                    else:
                        self._resolve_window(int(state["spot"] > self.strike))

        adverse_rate = sum(1 for f in self.fills if f.adverse) / max(len(self.fills), 1)
        net = self.bankroll - float(self.cfg["initial_capital_usdc"])
        report = {
            "verdict": "LOCAL_PAPER_ONLY",
            "verdict_binding": False,
            "demo_capital_usdc": float(self.cfg.get("initial_capital_usdc", 0)),
            "currency_label": self.cfg.get("currency_label", "USDC"),
            "demo_label": self.cfg.get("demo_label"),
            "strategy_id": self.strategy_id,
            "duration_minutes": minutes,
            "session_dir": str(self.out_dir),
            "fills": len(self.fills),
            "quotes_logged": self.quotes_logged,
            "nim_decisions_used": self.nim_decisions_used,
            "nim_rule_holds": self.nim_rule_holds,
            "nim_cache_hits": self.nim_cache_hits,
            "nim_last_latency_ms": self.last_nim_latency_ms,
            "nim_required": True,
            "spread_captured_usdc": round(self.spread_total, 2),
            "adverse_cost_usdc": round(self.adverse_total, 2),
            "bankroll_end_usdc": round(self.bankroll, 2),
            "net_session_usdc": round(net, 2),
            "adverse_rate": round(adverse_rate, 4),
            "paper_pnl_mode": self.cfg.get("paper_pnl_mode"),
            "warning": "Sesión local — no ingresos reales; no extrapolar a anual",
        }
        (self.out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        with fills_path.open("w", encoding="utf-8") as fh:
            for f in self.fills:
                fh.write(json.dumps(f.__dict__) + "\n")
        return report


def load_maker_cfg(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or MAKER_CFG
    return json.loads(path.read_text(encoding="utf-8"))


async def run_paper_session(
    strategy_id: str = "maker_16",
    minutes: float = 30.0,
    session_id: str | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    from polymarket.src.ai.env_loader import require_nvidia_api_key

    require_nvidia_api_key()
    if strategy_id not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy_id}. Choose from {list(STRATEGIES)}")
    cfg = load_maker_cfg(config_path)
    sid = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = OUT_BASE / strategy_id / f"session_{sid}"
    session = PaperSession(
        strategy_id=strategy_id,
        cfg=cfg,
        out_dir=out,
        bankroll=float(cfg["initial_capital_usdc"]),
    )
    return await session.run(minutes=minutes)
