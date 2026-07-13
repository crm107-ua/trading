#!/usr/bin/env python3
"""Phase A — long-running CLOB book recorder with 5m market rotation (PM2)."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any

from polymarket.research.collectors.market_discovery import (
    discover_btc_5m_updown,
    discovery_poll_seconds,
    pick_recording_targets,
    should_pre_subscribe,
    window_end,
    window_start,
)
from polymarket.research.collectors.recording_common import (
    GapTracker,
    HourlyJsonlWriter,
    PhaseAManifest,
    load_phase_a_config,
    manifest_interval_seconds,
    now_ns,
    resolve_data_root,
    truncate_book,
)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [clob_rec] %(message)s",
)
log = logging.getLogger(__name__)


class ClobRecorderDaemon:
    def __init__(self) -> None:
        self.cfg = load_phase_a_config()
        self.root = resolve_data_root(self.cfg)
        self.manifest_interval = manifest_interval_seconds(self.cfg)
        self.top_n = int(self.cfg.get("top_book_levels", 10))
        self.poll_s = float(self.cfg.get("discovery_poll_seconds", 30))
        self.pre_lead_s = float(self.cfg.get("pre_subscribe_lead_seconds", 60))
        self.writer = HourlyJsonlWriter(self.root, "clob", compress=True)
        self.gaps = GapTracker()
        self.manifest = PhaseAManifest(self.root, "clob", self.cfg)
        self._last_ts_ns = 0
        self._last_manifest = 0.0
        self._running = True
        self._token_id: str | None = None
        self._market_id: str | None = None
        self._market_question: str | None = None
        self._switches: list[dict[str, Any]] = []
        self._subscribed_tokens: list[str] = []
        self._ws_generation = 0
        self._active_market: Any = None
        self._next_market: Any = None
        self._inactive_open_ns: int | None = None
        self._market_inactive_periods: list[dict[str, int]] = []

    def _mark_market_inactive_start(self) -> None:
        if self._inactive_open_ns is None:
            self._inactive_open_ns = now_ns()

    def _mark_market_inactive_end(self) -> None:
        if self._inactive_open_ns is not None:
            self._market_inactive_periods.append(
                {"start_ns": self._inactive_open_ns, "end_ns": now_ns(), "reason": "gamma_no_active_window"}
            )
            self._inactive_open_ns = None

    def stop(self, *_args) -> None:
        self._running = False
        self._ws_generation += 1

    def _token_meta(self, token_id: str) -> tuple[str | None, str | None]:
        for m in (self._active_market, self._next_market):
            if m and m.token_id_up == token_id:
                return m.market_id, m.question
        return self._market_id, self._market_question

    async def _discovery_loop(self) -> None:
        while self._running:
            sleep_s = self.poll_s
            try:
                markets = await asyncio.to_thread(discover_btc_5m_updown)
                now = datetime.now(timezone.utc)
                active, nxt = pick_recording_targets(markets, now)
                self._active_market = active
                self._next_market = nxt
                sleep_s = discovery_poll_seconds(active, now, default=self.poll_s)

                if active is None and nxt is None:
                    self._mark_market_inactive_start()
                    log.info("No 5m window on Gamma yet; polling every %.0fs", sleep_s)
                else:
                    self._mark_market_inactive_end()
                if active is None and nxt is not None:
                    await self._switch_market(nxt, reason="initial")
                elif active is not None and self._token_id is None:
                    await self._switch_market(active, reason="initial")

                desired: list[str] = []
                if active is not None:
                    desired.append(active.token_id_up)
                if (
                    active is not None
                    and nxt is not None
                    and should_pre_subscribe(active, nxt, now, self.pre_lead_s)
                ):
                    nxt_start = window_start(nxt)
                    secs_to_open = (nxt_start - now).total_seconds() if nxt_start else None
                    log.info(
                        "Pre-subscribe to next window: %s (opens in %.0fs)",
                        nxt.question,
                        secs_to_open or -1,
                    )
                    if nxt.token_id_up not in desired:
                        desired.append(nxt.token_id_up)
                    if self._token_id != nxt.token_id_up:
                        await self._switch_market(nxt, reason="pre_subscribe")
                elif nxt is not None and active is not None:
                    ae = window_end(active)
                    if ae and (ae - now).total_seconds() <= 0 and self._token_id != nxt.token_id_up:
                        await self._switch_market(nxt, reason="rollover")

                if desired and set(desired) != set(self._subscribed_tokens):
                    self._subscribed_tokens = desired
                    self._ws_generation += 1
            except Exception as exc:  # noqa: BLE001
                log.error("Discovery error: %s", exc)
            await asyncio.sleep(sleep_s)

    async def _switch_market(self, market, reason: str = "switch") -> None:
        if market.token_id_up == self._token_id and reason != "pre_subscribe":
            return
        log.info("Switch market [%s] -> %s", reason, market.question)
        self._switches.append(
            {
                "ts_ns": now_ns(),
                "reason": reason,
                "market_id": market.market_id,
                "token_id_up": market.token_id_up,
                "question": market.question,
                "end_time": market.end_time,
                "window_start": window_start(market).isoformat() if window_start(market) else None,
            }
        )
        self._token_id = market.token_id_up
        self._market_id = market.market_id
        self._market_question = market.question
        self._ws_generation += 1

    async def run(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise SystemExit("pip install websockets") from exc

        discovery_task = asyncio.create_task(self._discovery_loop())
        backoff = 1.0
        max_backoff = float(self.cfg.get("ws_reconnect_backoff_max_seconds", 60))

        while self._running:
            if self._token_id is None:
                await asyncio.sleep(1.0)
                continue
            gen = self._ws_generation
            tokens = list(self._subscribed_tokens) if self._subscribed_tokens else [self._token_id]
            try:
                log.info("WS connect tokens=%s", [t[:12] + "..." for t in tokens])
                async with websockets.connect(WS_URL, open_timeout=15, ping_interval=20) as ws:
                    if self.gaps._open_start is not None:
                        self.gaps.mark_reconnect()
                    backoff = 1.0
                    sub = {"assets_ids": tokens, "type": "market"}
                    await ws.send(json.dumps(sub))
                    self._subscribed_tokens = tokens
                    while self._running and gen == self._ws_generation:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        except asyncio.TimeoutError:
                            continue
                        if not raw or not str(raw).strip():
                            continue
                        recv_ns = now_ns()
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            log.debug("Non-JSON WS frame: %r", raw[:80])
                            continue
                        items = payload if isinstance(payload, list) else [payload]
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            if item.get("event_type") != "book":
                                continue
                            asset = str(item.get("asset_id") or self._token_id)
                            mid, question = self._token_meta(asset)
                            ts_raw = item.get("timestamp")
                            if ts_raw:
                                ts_ns = (
                                    int(ts_raw) * 1_000_000
                                    if int(ts_raw) < 1e15
                                    else int(ts_raw)
                                )
                            else:
                                ts_ns = recv_ns
                            record = {
                                "ts_ns": ts_ns,
                                "recv_ts_ns": recv_ns,
                                "market_id": mid,
                                "token_id": asset,
                                "question": question,
                                "bids": truncate_book(item.get("bids") or [], self.top_n, side="bid"),
                                "asks": truncate_book(item.get("asks") or [], self.top_n, side="ask"),
                                "last_trade": item.get("last_trade_price"),
                                "source": "polymarket_clob_market",
                            }
                            self.writer.write(record)
                            self._last_ts_ns = recv_ns
                        if time.monotonic() - self._last_manifest >= self.manifest_interval:
                            self._flush_manifest()
            except Exception as exc:  # noqa: BLE001
                if not self._running:
                    break
                log.error("WS error: %s", exc)
                self.gaps.mark_disconnect()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

        discovery_task.cancel()
        self.writer.flush_to_disk()
        self.writer.close()
        self._flush_manifest()

    def _flush_manifest(self) -> None:
        self.writer.flush_to_disk()
        self.manifest.update_feed(
            last_ts_ns=self._last_ts_ns or now_ns(),
            rows_total=self.writer.rows_written,
            files=self.writer.files,
            gaps=self.gaps.gaps,
            extra={
                "current_market_id": self._market_id,
                "current_token_id": self._token_id,
                "current_question": self._market_question,
                "subscribed_tokens": self._subscribed_tokens,
                "market_switches": self._switches[-50:],
                "market_inactive_periods": self._market_inactive_periods[-50:],
                "top_book_levels": self.top_n,
            },
        )
        self._last_manifest = time.monotonic()
        log.info("Manifest updated rows=%s switches=%s", self.writer.rows_written, len(self._switches))


def main() -> None:
    daemon = ClobRecorderDaemon()
    signal.signal(signal.SIGINT, daemon.stop)
    signal.signal(signal.SIGTERM, daemon.stop)
    try:
        asyncio.run(daemon.run())
    finally:
        log.info("Stopped")


if __name__ == "__main__":
    main()
