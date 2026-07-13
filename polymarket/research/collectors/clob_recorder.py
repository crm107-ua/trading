"""CLOB WebSocket depth recorder."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from polymarket.research.collectors.market_discovery import discover_btc_updown
from polymarket.src.data import write_manifest

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


async def record_book(token_id: str, duration_s: float, out_path: Path) -> int:
    try:
        import websockets
    except ImportError as exc:
        raise SystemExit("websockets required") from exc

    snapshots: list[dict] = []
    async with websockets.connect(WS_URL, open_timeout=10) as ws:
        await ws.send(json.dumps({"assets_ids": [token_id], "type": "market"}))
        deadline = time.perf_counter() + duration_s
        while time.perf_counter() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                payload = json.loads(raw)
                items = payload if isinstance(payload, list) else [payload]
                for item in items:
                    if isinstance(item, dict) and item.get("event_type") == "book":
                        snapshots.append(
                            {
                                "ts_ms": int(item.get("timestamp") or time.time() * 1000),
                                "bids": item.get("bids") or [],
                                "asks": item.get("asks") or [],
                                "last_trade": item.get("last_trade_price"),
                            }
                        )
            except asyncio.TimeoutError:
                break
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshots), encoding="utf-8")
    return len(snapshots)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--token-id", default=None)
    args = p.parse_args()
    token_id = args.token_id
    if not token_id:
        markets = discover_btc_updown()
        if not markets:
            raise SystemExit("No active BTC Up/Down markets found")
        token_id = markets[0].token_id_up
    dataset_id = f"clob_rec_{int(time.time())}"
    base = Path(__file__).resolve().parents[2] / "data_local" / dataset_id
    out = base / "book_snapshots.json"
    n = asyncio.run(record_book(token_id, args.duration, out))
    write_manifest(
        dataset_id,
        {
            "source": "clob_ws_market",
            "token_id": token_id,
            "duration_s": args.duration,
            "rows": n,
            "file": out.name,
        },
    )
    print(f"Recorded {n} book snapshots -> {out}")


if __name__ == "__main__":
    main()
