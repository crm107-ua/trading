#!/usr/bin/env python3
"""Phase A — long-running Binance BTC trade feed (PM2)."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path

from polymarket.research.collectors.recording_common import (
    GapTracker,
    HourlyJsonlWriter,
    PhaseAManifest,
    load_phase_a_config,
    manifest_interval_seconds,
    now_ns,
    resolve_data_root,
)

BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [btc_feed] %(message)s",
)
log = logging.getLogger(__name__)


class BtcFeedDaemon:
    def __init__(self) -> None:
        self.cfg = load_phase_a_config()
        self.root = resolve_data_root(self.cfg)
        self.manifest_interval = manifest_interval_seconds(self.cfg)
        self.writer = HourlyJsonlWriter(self.root, "btc", compress=True)
        self.gaps = GapTracker()
        self.manifest = PhaseAManifest(self.root, "btc", self.cfg)
        self._last_ts_ns = 0
        self._last_manifest = 0.0
        self._running = True

    def stop(self, *_args) -> None:
        self._running = False

    async def run(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise SystemExit("pip install websockets") from exc

        backoff = 1.0
        max_backoff = float(self.cfg.get("ws_reconnect_backoff_max_seconds", 60))

        while self._running:
            try:
                log.info("Connecting %s", BINANCE_WS)
                async with websockets.connect(BINANCE_WS, open_timeout=15, ping_interval=20) as ws:
                    if self.gaps._open_start is not None:
                        self.gaps.mark_reconnect()
                        log.warning("Reconnected after gap")
                    backoff = 1.0
                    while self._running:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        except asyncio.TimeoutError:
                            continue
                        recv_ns = now_ns()
                        msg = json.loads(raw)
                        ts_ns = int((msg.get("T") or msg.get("E") or recv_ns / 1_000_000) * 1_000_000)
                        record = {
                            "ts_ns": ts_ns,
                            "recv_ts_ns": recv_ns,
                            "price": float(msg["p"]),
                            "qty": float(msg["q"]),
                            "source": "binance_btcusdt_trade",
                        }
                        self.writer.write(record)
                        self._last_ts_ns = recv_ns
                        if time.monotonic() - self._last_manifest >= self.manifest_interval:
                            self._flush_manifest()
            except Exception as exc:  # noqa: BLE001
                log.error("WS error: %s", exc)
                self.gaps.mark_disconnect()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

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
        )
        self._last_manifest = time.monotonic()
        log.info("Manifest updated rows=%s files=%s gaps=%s", self.writer.rows_written, len(self.writer.files), len(self.gaps.gaps))


def main() -> None:
    daemon = BtcFeedDaemon()
    signal.signal(signal.SIGINT, daemon.stop)
    signal.signal(signal.SIGTERM, daemon.stop)
    try:
        asyncio.run(daemon.run())
    finally:
        log.info("Stopped")


if __name__ == "__main__":
    main()
