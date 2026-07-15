#!/usr/bin/env python3
"""
Paper maker local — simula cotizaciones y fills sin on-chain.

Salida: polymarket/data_local/local_lab/<strategy>/session_<id>/
NO es screen fase B/C. NO proyectar ingresos anuales desde aquí.
"""

from __future__ import annotations

import asyncio
import json
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
from polymarket.src.pricing.fair_value import estimate_fair_values
from polymarket.src.signals.features import build_market_features
from polymarket.src.ai.decision_engine import Decision, decide_quote_action
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

    def _strategy_fn(self):
        fn = STRATEGIES[self.strategy_id]
        if self.strategy_id == "maker_16":
            return lambda fair, bb, ba, spot, strike: fn(fair, self.cfg)
        return lambda fair, bb, ba, spot, strike: fn(fair, bb, ba, spot, strike, self.cfg)

    def _maker_quotes(self, fair: float, bb: float | None, ba: float | None, spot: float) -> QuoteIntent | None:
        return self._strategy_fn()(fair, bb, ba, spot, self.strike or spot)

    def _resolve_window(self, resolved_up: int) -> float:
        if abs(self.inventory_shares) < 1e-9:
            return 0.0
        payout = self.inventory_shares * resolved_up
        pnl = payout - self.cost_basis
        self.bankroll += payout
        self.inventory_shares = 0.0
        self.cost_basis = 0.0
        return pnl

    def _check_fill(self, last_trade: float | None, quote: QuoteIntent, fair: float, spot: float) -> None:
        if last_trade is None:
            return
        if self.last_trade_seen is not None and abs(last_trade - self.last_trade_seen) < 1e-9:
            return
        self.last_trade_seen = last_trade
        side = None
        price = None
        if abs(last_trade - quote.bid) <= 0.02:
            side, price = "bid", quote.bid
        elif abs(last_trade - quote.ask) <= 0.02:
            side, price = "ask", quote.ask
        if side is None:
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
        adv_cost = spread_cap if adverse else 0.0
        self.spread_total += spread_cap
        self.adverse_total += adv_cost
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

    async def _fetch_state(self, token_id: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=12.0) as client:
            br = await client.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": "BTCUSDT"},
            )
            cr = await client.get(
                "https://clob.polymarket.com/book",
                params={"token_id": token_id},
            )
        if cr.status_code != 200:
            return None
        book = cr.json()
        spot = float(br.json()["price"])
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
        poll_s = 2.0
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
                        resolved = int(state["spot"] > self.strike)
                        self._resolve_window(resolved)
                prev_market = target.market_id
                self.current_market_id = target.market_id
                self.current_question = target.question
                ws = window_start(target)
                we = window_end(target)
                self.window_end_ns = int(we.timestamp() * 1e9) if we else None
                async with httpx.AsyncClient(timeout=12.0) as c:
                    r = await c.get(
                        "https://api.binance.com/api/v3/ticker/price",
                        params={"symbol": "BTCUSDT"},
                    )
                    self.strike = float(r.json()["price"])
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
            fair = estimate_fair_values(feats)["up"]
            if self.last_quote_spot is None or abs(state["spot"] - self.last_quote_spot) >= requote_move:
                self.last_quote_spot = state["spot"]
            quote = self._maker_quotes(fair, state["best_bid"], state["best_ask"], state["spot"])
            if quote is None:
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
                "max_inventory_usdc": float(self.cfg["max_inventory_usdc"]),
                "kill_switch_feed_stale_ms": float(self.cfg["kill_switch_feed_stale_ms"]),
                "feed_age_ms": feed_age_ms,
                "quote_bid": quote.bid,
                "quote_ask": quote.ask,
                "quote_size": quote.size_shares,
            }
            decision, nim = decide_quote_action(snapshot=snap, latency_budget_ms=750)
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
            self._check_fill(state["last_trade"], quote, fair, state["spot"])
            await asyncio.sleep(poll_s)

        # Resolve open inventory at session end
        if abs(self.inventory_shares) > 1e-9 and self.strike is not None:
            markets = await asyncio.to_thread(discover_btc_5m_updown)
            active, nxt = pick_recording_targets(markets, datetime.now(timezone.utc))
            target = active or nxt
            if target:
                state = await self._fetch_state(target.token_id_up)
                if state:
                    self._resolve_window(int(state["spot"] > self.strike))

        adverse_rate = sum(1 for f in self.fills if f.adverse) / max(len(self.fills), 1)
        net = self.bankroll - float(self.cfg["initial_capital_usdc"])
        report = {
            "verdict": "LOCAL_PAPER_ONLY",
            "verdict_binding": False,
            "demo_capital_usdc": float(self.cfg.get("initial_capital_usdc", 0)),
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
