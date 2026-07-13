#!/usr/bin/env python3
"""Fase 0 — probes Gamma, CLOB REST, prices-history, latencia básica."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
OUT = Path(__file__).resolve().parents[1] / "data_local" / "phase0_probe.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_active_btc_updown(client: httpx.Client) -> dict[str, Any]:
    """Public-search for active Bitcoin Up or Down events."""
    t0 = time.perf_counter()
    r = client.get(
        f"{GAMMA}/public-search",
        params={"q": "Bitcoin Up or Down", "events_status": "active"},
        timeout=20.0,
    )
    r.raise_for_status()
    events = r.json().get("events") or []
    btc = [e for e in events if "bitcoin" in (e.get("title") or "").lower()]
    sample_market = None
    token_id = None
    if btc:
        markets = btc[0].get("markets") or []
        if markets:
            sample_market = markets[0]
            tids = sample_market.get("clobTokenIds")
            if isinstance(tids, str):
                tids = json.loads(tids)
            token_id = str(tids[0]) if tids else None
    return {
        "ok": len(btc) > 0,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        "active_events": len(btc),
        "sample_title": btc[0].get("title") if btc else None,
        "sample_question": (sample_market or {}).get("question"),
        "token_id": token_id,
        "accepting_orders": (sample_market or {}).get("acceptingOrders"),
    }


def probe_clob_book(client: httpx.Client, token_id: str | None) -> dict[str, Any]:
    if not token_id:
        return {"ok": False, "reason": "no_token_id"}
    t0 = time.perf_counter()
    r = client.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=15.0)
    if r.status_code == 404:
        return {"ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "reason": "no_orderbook"}
    r.raise_for_status()
    book = r.json()
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    best_bid = float(bids[0]["price"]) if bids else None
    best_ask = float(asks[0]["price"]) if asks else None
    mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
    return {
        "ok": True,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
    }


def probe_prices_history(client: httpx.Client, token_id: str | None) -> dict[str, Any]:
    if not token_id:
        return {"ok": False, "reason": "no_token_id"}
    t0 = time.perf_counter()
    r = client.get(
        f"{CLOB}/prices-history",
        params={"market": token_id, "interval": "1d", "fidelity": 60},
        timeout=20.0,
    )
    ok = r.status_code == 200
    data = r.json() if ok else {"error": r.text[:200]}
    history = data.get("history") if isinstance(data, dict) else None
    return {
        "ok": ok,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        "points": len(history) if history else 0,
        "note": "mid-only; no depth history",
        "sample_tail": (history or [])[-2:],
    }


async def probe_ws_market(token_id: str | None, duration_s: float = 5.0) -> dict[str, Any]:
    if not token_id:
        return {"ok": False, "reason": "no_token_id"}
    try:
        import websockets
    except ImportError:
        return {"ok": False, "reason": "websockets_not_installed"}

    messages: list[Any] = []
    t0 = time.perf_counter()
    try:
        async with websockets.connect(WS_URL, open_timeout=10) as ws:
            sub = {"assets_ids": [token_id], "type": "market"}
            await ws.send(json.dumps(sub))
            deadline = time.perf_counter() + duration_s
            while time.perf_counter() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    payload = json.loads(raw)
                    if isinstance(payload, list):
                        messages.extend(payload)
                    else:
                        messages.append(payload)
                except asyncio.TimeoutError:
                    break
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

    book_msgs = [m for m in messages if isinstance(m, dict) and m.get("event_type") == "book"]
    return {
        "ok": len(messages) > 0,
        "duration_s": duration_s,
        "message_count": len(messages),
        "book_updates": len(book_msgs),
        "connect_plus_first_msg_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def probe_binance_rtt(client: httpx.Client, n: int = 5) -> dict[str, Any]:
    rtts = []
    price = None
    for _ in range(n):
        t0 = time.perf_counter()
        r = client.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": "BTCUSDT"},
            timeout=10.0,
        )
        r.raise_for_status()
        rtts.append((time.perf_counter() - t0) * 1000)
        price = r.json().get("price")
    return {
        "ok": True,
        "rtt_ms": {
            "p50": round(statistics.median(rtts), 1),
            "p95": round(sorted(rtts)[max(0, int(len(rtts) * 0.95) - 1)], 1),
            "samples": [round(x, 1) for x in rtts],
        },
        "btc_price": price,
    }


def probe_spot_clob_pair(client: httpx.Client, token_id: str | None, n: int = 5) -> dict[str, Any]:
    if not token_id:
        return {"ok": False, "reason": "no_token_id"}
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        br = client.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": "BTCUSDT"},
            timeout=10.0,
        )
        t1 = time.perf_counter()
        cr = client.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=10.0)
        t2 = time.perf_counter()
        book = cr.json() if cr.status_code == 200 else {}
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        mid = None
        if bids and asks:
            mid = (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
        samples.append(
            {
                "binance_ms": round((t1 - t0) * 1000, 1),
                "clob_ms": round((t2 - t1) * 1000, 1),
                "mid": mid,
            }
        )
        time.sleep(0.2)
    clob_ms = [s["clob_ms"] for s in samples]
    return {
        "ok": True,
        "samples": samples,
        "clob_rtt_p50": round(statistics.median(clob_ms), 1),
        "clob_rtt_p95": round(sorted(clob_ms)[-1], 1),
    }


def run_probes() -> dict[str, Any]:
    report: dict[str, Any] = {"timestamp_utc": _now(), "checks": {}}
    with httpx.Client(headers={"User-Agent": "polymarket-lab/0.1"}) as client:
        discovery = find_active_btc_updown(client)
        report["checks"]["gamma_search"] = discovery
        token_id = discovery.get("token_id")
        report["token_id_used"] = token_id
        report["checks"]["clob_book"] = probe_clob_book(client, token_id)
        report["checks"]["prices_history"] = probe_prices_history(client, token_id)
        report["checks"]["binance_rtt"] = probe_binance_rtt(client)
        report["checks"]["spot_clob_pair"] = probe_spot_clob_pair(client, token_id)
    report["checks"]["clob_ws"] = asyncio.run(probe_ws_market(token_id))
    return report


def main() -> None:
    report = run_probes()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
