"""Load and align phase-A JSONL panels (BTC + CLOB)."""

from __future__ import annotations

import gzip
import json
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from polymarket.src.data.book_utils import best_bid_ask

ET = ZoneInfo("America/New_York")

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

_WINDOW_ET = re.compile(
    r"(\w+)\s+(\d{1,2}),\s*(\d{1,2}):(\d{2})\s*(AM|PM)\s*-\s*"
    r"(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET",
    re.IGNORECASE,
)


def _clock(h: int, m: int, ap: str) -> tuple[int, int]:
    ap = ap.upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return h, m


def parse_window_bounds(question: str) -> tuple[datetime, datetime] | None:
    m = _WINDOW_ET.search(question)
    if not m:
        return None
    month_s, day_s, h1, m1, ap1, h2, m2, ap2 = m.groups()
    month = _MONTHS.get(month_s.lower())
    if not month:
        return None
    day = int(day_s)
    sh, sm = _clock(int(h1), int(m1), ap1)
    eh, em = _clock(int(h2), int(m2), ap2)
    year = datetime.now(ET).year
    start = datetime(year, month, day, sh, sm, tzinfo=ET)
    end = datetime(year, month, day, eh, em, tzinfo=ET)
    if end <= start:
        end = end.replace(day=end.day + 1) if end.hour < start.hour else end
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _read_jsonl_gz(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)
    except EOFError:
        return


def load_panel(data_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    btc_rows: list[dict[str, Any]] = []
    clob_rows: list[dict[str, Any]] = []
    for path in sorted((data_root / "btc").rglob("*.jsonl.gz")):
        btc_rows.extend(_read_jsonl_gz(path))
    for path in sorted((data_root / "clob").rglob("*.jsonl.gz")):
        clob_rows.extend(_read_jsonl_gz(path))
    btc_rows.sort(key=lambda r: r.get("recv_ts_ns", 0))
    clob_rows.sort(key=lambda r: r.get("recv_ts_ns", 0))
    return btc_rows, clob_rows


def _load_manifest_windows(data_root: Path) -> dict[str, dict[str, Any]]:
    path = data_root / "manifest.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for sw in data.get("feeds", {}).get("clob", {}).get("market_switches", []):
        mid = str(sw.get("market_id", ""))
        if mid:
            out[mid] = sw
    return out


@dataclass
class AlignedTick:
    recv_ts_ns: int
    market_id: str
    question: str
    spot: float
    strike: float
    time_remaining_s: float
    bids: list[dict]
    asks: list[dict]
    best_bid: float | None
    best_ask: float | None
    last_trade: float | None
    window_start_ns: int
    window_end_ns: int


@dataclass
class ReplayPanel:
    ticks: list[AlignedTick] = field(default_factory=list)
    windows: dict[str, dict[str, Any]] = field(default_factory=dict)
    btc_count: int = 0
    clob_count: int = 0
    duration_hours: float = 0.0


def build_replay_panel(data_root: Path) -> ReplayPanel:
    btc_rows, clob_rows = load_panel(data_root)
    panel = ReplayPanel(btc_count=len(btc_rows), clob_count=len(clob_rows))
    if not btc_rows or not clob_rows:
        return panel

    btc_ts = [r["recv_ts_ns"] for r in btc_rows]
    btc_prices = [float(r["price"]) for r in btc_rows]
    panel.duration_hours = (btc_ts[-1] - btc_ts[0]) / 1_000_000_000 / 3600
    manifest_sw = _load_manifest_windows(data_root)

    by_market: dict[str, list[dict]] = {}
    for row in clob_rows:
        by_market.setdefault(str(row.get("market_id") or ""), []).append(row)

    for market_id, rows in by_market.items():
        question = rows[0].get("question") or ""
        bounds = parse_window_bounds(question)
        sw = manifest_sw.get(market_id, {})
        if bounds:
            ws, we = bounds
            ws_ns = int(ws.timestamp() * 1_000_000_000)
            we_ns = int(we.timestamp() * 1_000_000_000)
        elif sw.get("window_start") and sw.get("end_time"):
            ws = datetime.fromisoformat(sw["window_start"].replace("Z", "+00:00"))
            we = datetime.fromisoformat(sw["end_time"].replace("Z", "+00:00"))
            ws_ns = int(ws.timestamp() * 1_000_000_000)
            we_ns = int(we.timestamp() * 1_000_000_000)
        else:
            ws_ns = rows[0]["recv_ts_ns"]
            we_ns = ws_ns + 300_000_000_000

        idx = max(bisect_right(btc_ts, ws_ns) - 1, 0)
        strike = btc_prices[idx]
        idx_end = max(bisect_right(btc_ts, we_ns) - 1, 0)
        spot_end = btc_prices[min(idx_end, len(btc_prices) - 1)]
        resolved_up = int(spot_end > strike)

        panel.windows[market_id] = {
            "market_id": market_id,
            "question": question,
            "window_start_ns": ws_ns,
            "window_end_ns": we_ns,
            "strike": strike,
            "spot_end": spot_end,
            "resolved_up": resolved_up,
            "clob_updates": len(rows),
        }

        for row in rows:
            recv_ns = int(row["recv_ts_ns"])
            if recv_ns < ws_ns or recv_ns > we_ns:
                continue
            bi = bisect_right(btc_ts, recv_ns) - 1
            if bi < 0:
                continue
            spot = btc_prices[bi]
            bids = row.get("bids") or []
            asks = row.get("asks") or []
            bb, ba = best_bid_ask(bids, asks)
            lt = row.get("last_trade")
            panel.ticks.append(
                AlignedTick(
                    recv_ts_ns=recv_ns,
                    market_id=market_id,
                    question=question,
                    spot=spot,
                    strike=strike,
                    time_remaining_s=max((we_ns - recv_ns) / 1_000_000_000, 1.0),
                    bids=bids,
                    asks=asks,
                    best_bid=bb,
                    best_ask=ba,
                    last_trade=float(lt) if lt is not None else None,
                    window_start_ns=ws_ns,
                    window_end_ns=we_ns,
                )
            )

    panel.ticks.sort(key=lambda t: t.recv_ts_ns)
    return panel
