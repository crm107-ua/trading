"""External BTC spot feed (Binance WS one-shot or REST poll)."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from polymarket.src.data import write_manifest
from polymarket.src.data.btc_spot import fetch_btc_spot_rest

BINANCE_REST = "https://api.binance.com/api/v3/ticker/price"
BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"


def fetch_btc_price_rest() -> tuple[float, float]:
    price, latency_ms, _source = fetch_btc_spot_rest(timeout=10.0)
    return price, latency_ms


async def record_trades(duration_s: float, out_path: Path) -> int:
    try:
        import websockets
    except ImportError as exc:
        raise SystemExit("websockets required") from exc

    rows: list[dict] = []
    async with websockets.connect(BINANCE_WS, open_timeout=10) as ws:
        deadline = time.perf_counter() + duration_s
        while time.perf_counter() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                rows.append(
                    {
                        "ts_ms": msg.get("T") or msg.get("E"),
                        "price": float(msg["p"]),
                        "qty": float(msg["q"]),
                    }
                )
            except asyncio.TimeoutError:
                break
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows), encoding="utf-8")
    return len(rows)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=10.0)
    args = p.parse_args()
    price, lat = fetch_btc_price_rest()
    dataset_id = f"btc_feed_{int(time.time())}"
    out = Path(__file__).resolve().parents[2] / "data_local" / dataset_id / "trades.json"
    n = asyncio.run(record_trades(args.duration, out))
    write_manifest(
        dataset_id,
        {
            "source": "binance_ws_btcusdt@trade",
            "duration_s": args.duration,
            "rows": n,
            "rest_snapshot_price": price,
            "rest_latency_ms": round(lat, 1),
            "file": str(out.name),
        },
    )
    print(f"Recorded {n} trades -> {out}")


if __name__ == "__main__":
    main()
