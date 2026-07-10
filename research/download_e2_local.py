#!/usr/bin/env python3
"""Descarga 1d del universo E2 a research/data_local/ (sin Docker, solo API Binance)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTDIR = ROOT / "research" / "data_local" / "binance"
MANIFEST = ROOT / "research" / "data_local" / "e2_download_manifest.json"

# Universo E2 (mismo que xsec_momentum_core.XSEC_UNIVERSE_ASSETS)
E2_ASSETS = (
  "AAVE",
  "ADA",
  "BNB",
  "BTC",
  "DEXE",
  "DOGE",
  "ETH",
  "LTC",
  "NEAR",
  "SKL",
  "SOL",
  "TRX",
  "UNI",
  "XLM",
  "XRP",
  "ZEC",
)

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
START_MS = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)


def fetch_klines_1d(symbol: str, *, start_ms: int = START_MS) -> pd.DataFrame:
  """Pagina klines 1d de Binance spot hasta hoy."""
  rows: list[list] = []
  cursor = start_ms
  with httpx.Client(timeout=30.0) as client:
    while True:
      resp = client.get(
        BINANCE_KLINES,
        params={"symbol": symbol, "interval": "1d", "startTime": cursor, "limit": 1000},
      )
      resp.raise_for_status()
      batch = resp.json()
      if not batch:
        break
      rows.extend(batch)
      last_open = int(batch[-1][0])
      next_cursor = last_open + 86_400_000
      if next_cursor <= cursor or len(batch) < 1000:
        break
      cursor = next_cursor
      time.sleep(0.15)
  if not rows:
    raise RuntimeError(f"sin klines para {symbol}")
  df = pd.DataFrame(
    rows,
    columns=[
      "open_time",
      "open",
      "high",
      "low",
      "close",
      "volume",
      "close_time",
      "quote_volume",
      "trades",
      "taker_buy_base",
      "taker_buy_quote",
      "ignore",
    ],
  )
  out = pd.DataFrame(
    {
      "date": pd.to_datetime(df["open_time"], unit="ms", utc=True),
      "open": df["open"].astype(float),
      "high": df["high"].astype(float),
      "low": df["low"].astype(float),
      "close": df["close"].astype(float),
      "volume": df["volume"].astype(float),
    }
  )
  return out.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def main() -> int:
  pairs = [f"{a}/USDT" for a in E2_ASSETS]
  OUTDIR.mkdir(parents=True, exist_ok=True)
  manifest_rows: list[dict] = []
  for pair in pairs:
    symbol = pair.replace("/", "")
    out_path = OUTDIR / f"{pair.replace('/', '_')}-1d.feather"
    print(f"Descargando {pair} -> {out_path.name}")
    try:
      df = fetch_klines_1d(symbol)
      df.to_feather(out_path)
      manifest_rows.append(
        {
          "pair": pair,
          "rows": len(df),
          "start": str(df["date"].min().date()),
          "end": str(df["date"].max().date()),
          "path": str(out_path.relative_to(ROOT)),
        }
      )
    except Exception as exc:
      print(f"  ERROR {pair}: {exc}", file=sys.stderr)
      manifest_rows.append({"pair": pair, "error": str(exc)})
  MANIFEST.write_text(
    json.dumps(
      {
        "source": "binance_api_v3_klines",
        "timeframe": "1d",
        "pairs_requested": pairs,
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": manifest_rows,
      },
      indent=2,
    ),
    encoding="utf-8",
  )
  ok = sum(1 for x in manifest_rows if "rows" in x)
  print(f"Hecho: {ok}/{len(pairs)} pares en {OUTDIR}")
  print(f"Manifiesto: {MANIFEST}")
  return 0 if ok == len(pairs) else 1


if __name__ == "__main__":
  raise SystemExit(main())
