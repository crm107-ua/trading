#!/usr/bin/env python3
"""
Scan Polymarket leaderboard wallets and score copy-trade candidates.

Honest framing: no wallet "never loses". We rank by event/trade quality and
surface styles (weather ladder vs micro-flip vs other).

  python -m polymarket.research.local_lab.elite_wallet_scan --limit 40
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "copy_research"
SLUG_TEMP = re.compile(r"(highest|lowest)-temperature-in-", re.I)
DATA = "https://data-api.polymarket.com"


def _leaderboard(client: httpx.Client, *, time_period: str, limit: int) -> list[dict[str, Any]]:
    r = client.get(
        f"{DATA}/v1/leaderboard",
        params={
            "category": "overall",
            "timePeriod": time_period,
            "orderBy": "PNL",
            "limit": limit,
        },
    )
    r.raise_for_status()
    return list(r.json() or [])


def _closed(client: httpx.Client, addr: str, *, max_rows: int = 80) -> list[dict[str, Any]]:
    """Fetch closed positions from BOTH PnL tails.

    The default endpoint ordering is winner-heavy; without ASC+DESC pulls,
    almost every leaderboard wallet falsely looks like WR=100%.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for direction in ("DESC", "ASC"):
        offset = 0
        while offset < max_rows // 2:
            r = client.get(
                f"{DATA}/closed-positions",
                params={
                    "user": addr,
                    "limit": 40,
                    "offset": offset,
                    "sortBy": "REALIZEDPNL",
                    "sortDirection": direction,
                },
            )
            if r.status_code != 200:
                break
            batch = r.json() or []
            if not batch:
                break
            for p in batch:
                key = f"{p.get('conditionId')}|{p.get('asset')}|{p.get('outcomeIndex')}|{p.get('realizedPnl')}"
                if key in seen:
                    continue
                seen.add(key)
                rows.append(p)
            offset += len(batch)
            if len(batch) < 40:
                break
    return rows


def _activity(client: httpx.Client, addr: str, *, max_rows: int = 120) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < max_rows:
        r = client.get(
            f"{DATA}/activity",
            params={"user": addr, "limit": 50, "offset": offset},
        )
        if r.status_code != 200:
            break
        batch = r.json() or []
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if len(batch) < 50:
            break
    return rows


def _score_wallet(addr: str, name: str, pnl_lb: float, closed: list[dict], acts: list[dict]) -> dict[str, Any]:
    pnls = [float(p.get("realizedPnl") or 0) for p in closed]
    wins = sum(1 for x in pnls if x > 0)
    losses = sum(1 for x in pnls if x < 0)
    n = wins + losses
    wr = (wins / n) if n else None
    total = sum(pnls)
    avg_px = [float(p.get("avgPrice") or 0) for p in closed if p.get("avgPrice") is not None]
    temp_n = sum(1 for p in closed if SLUG_TEMP.search(str(p.get("eventSlug") or p.get("slug") or "")))
    trades = [a for a in acts if a.get("type") == "TRADE"]
    buys = sum(1 for a in trades if a.get("side") == "BUY")
    sells = sum(1 for a in trades if a.get("side") == "SELL")
    trade_px = [float(a.get("price") or 0) for a in trades if a.get("price") is not None]
    # Micro-flip heuristic: many sells + prices clustered near 0.45-0.55
    mid_band = sum(1 for p in trade_px if 0.45 <= p <= 0.55)
    style = "other"
    if temp_n >= max(5, 0.35 * max(len(closed), 1)):
        style = "weather_ladder"
    elif sells >= 8 and mid_band >= max(5, 0.25 * max(len(trade_px), 1)):
        style = "micro_spread_like"
    elif sells >= buys * 0.35 and len(trades) >= 20:
        style = "active_mm_or_flip"

    # Copy score: reject "never lose" myth; require sample + positive pnl + decent WR
    copy_score = -1e9
    if n >= 15 and total > 0 and wr is not None:
        copy_score = (
            120.0 * wr
            + 0.002 * min(total, 50_000)
            + 15.0 * min(n, 80) / 80.0
            + (40.0 if style in ("weather_ladder", "micro_spread_like") else 0.0)
            - (80.0 if wr < 0.45 else 0.0)
        )
    return {
        "address": addr,
        "name": name,
        "leaderboard_pnl": round(float(pnl_lb), 2),
        "closed_n": len(closed),
        "decided_n": n,
        "wins": wins,
        "losses": losses,
        "winrate": round(wr, 4) if wr is not None else None,
        "realized_pnl_sample": round(total, 2),
        "median_avg_price": round(statistics.median(avg_px), 4) if avg_px else None,
        "temp_market_share": round(temp_n / len(closed), 4) if closed else 0.0,
        "trades_sample": len(trades),
        "buy_sell": {"buy": buys, "sell": sells},
        "mid_band_trade_share": round(mid_band / len(trade_px), 4) if trade_px else None,
        "style": style,
        "copy_score": round(copy_score, 3),
        "never_loses": False,  # explicit: never claim this
        "copy_candidate": bool(copy_score > 80 and wr is not None and wr >= 0.5 and total > 100),
    }


def scan(*, limit: int, period: str) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    with httpx.Client(timeout=40.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        board = _leaderboard(client, time_period=period, limit=limit)
        # Also merge day board for "overnight" narrative wallets
        try:
            day = _leaderboard(client, time_period="day", limit=min(20, limit))
        except Exception:
            day = []
        seen: set[str] = set()
        wallets: list[dict[str, Any]] = []
        for row in board + day:
            addr = str(row.get("proxyWallet") or "").lower()
            if not addr or addr in seen:
                continue
            seen.add(addr)
            name = str(row.get("userName") or addr[:10])
            print(f"scoring {name} {addr[:12]}…", flush=True)
            closed = _closed(client, addr)
            acts = _activity(client, addr)
            wallets.append(_score_wallet(addr, name, float(row.get("pnl") or 0), closed, acts))

    wallets.sort(key=lambda w: w["copy_score"], reverse=True)
    candidates = [w for w in wallets if w.get("copy_candidate")]
    styles = collections.Counter(w["style"] for w in wallets)
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "scanned": len(wallets),
        "candidates": len(candidates),
        "styles": dict(styles),
        "myth_check": {
            "claim": "wallets that never lose",
            "found_never_lose_with_n15": sum(
                1 for w in wallets if (w.get("decided_n") or 0) >= 15 and (w.get("losses") or 0) == 0
            ),
            "note": "Elite copy needs positive expectancy + sample, not 100% WR myths.",
        },
        "top": wallets[:25],
        "copy_watchlist": candidates[:15],
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }
    path = OUT / f"elite_scan_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "elite_watchlist.json").write_text(
        json.dumps({"ts_utc": report["ts_utc"], "watchlist": report["copy_watchlist"]}, indent=2),
        encoding="utf-8",
    )
    report["path"] = str(path)
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=35)
    p.add_argument("--period", default="month", choices=["day", "week", "month", "all"])
    args = p.parse_args()
    rep = scan(limit=int(args.limit), period=str(args.period))
    slim = {
        "scanned": rep["scanned"],
        "candidates": rep["candidates"],
        "styles": rep["styles"],
        "myth_check": rep["myth_check"],
        "top5": [
            {k: w[k] for k in ("name", "style", "winrate", "realized_pnl_sample", "copy_score", "copy_candidate")}
            for w in rep["top"][:5]
        ],
        "path": rep["path"],
    }
    print(json.dumps(slim, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
