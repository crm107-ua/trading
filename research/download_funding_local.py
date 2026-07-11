#!/usr/bin/env python3
"""
Descarga histórico de funding rates de Binance USDT-perpetuals (universo E2)
a research/data_local/funding/ (gitignored).

NOTA: dato de FUTUROS usado como señal para operar SPOT. El funding se paga
cada 8h (3 registros/día). Cobertura variable por par: BTC/ETH desde ~2019,
altcoins desde su listing en futuros (puede ser años después del spot).
Pares sin perpetual (p. ej. DEXE) quedan registrados en el manifest como ausentes.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTDIR = ROOT / "research" / "data_local" / "funding"
MANIFEST = OUTDIR / "funding_manifest.json"

E2_ASSETS = (
  "AAVE", "ADA", "BNB", "BTC", "DEXE", "DOGE", "ETH", "LTC",
  "NEAR", "SKL", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC",
)

FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
START_MS = int(pd.Timestamp("2019-09-01", tz="UTC").timestamp() * 1000)


def fetch_funding_history(symbol: str, client: httpx.Client) -> pd.DataFrame | None:
  rows: list[dict] = []
  cursor = START_MS
  while True:
    resp = client.get(
      FUNDING_URL,
      params={"symbol": symbol, "startTime": cursor, "limit": 1000},
    )
    if resp.status_code == 400:
      # símbolo sin perpetual
      return None
    resp.raise_for_status()
    batch = resp.json()
    if not batch:
      break
    rows.extend(batch)
    last = int(batch[-1]["fundingTime"])
    next_cursor = last + 1
    if next_cursor <= cursor or len(batch) < 1000:
      break
    cursor = next_cursor
    time.sleep(0.12)
  if not rows:
    return None
  df = pd.DataFrame(rows)
  out = pd.DataFrame(
    {
      "funding_time": pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True),
      "funding_rate": df["fundingRate"].astype(float),
    }
  )
  return out.drop_duplicates(subset=["funding_time"]).sort_values("funding_time").reset_index(drop=True)


def main() -> int:
  OUTDIR.mkdir(parents=True, exist_ok=True)
  manifest: list[dict] = []
  with httpx.Client(timeout=30.0) as client:
    for asset in E2_ASSETS:
      symbol = f"{asset}USDT"
      pair = f"{asset}/USDT"
      print(f"Funding {symbol} ...", flush=True)
      try:
        df = fetch_funding_history(symbol, client)
      except Exception as exc:
        print(f"  ERROR {symbol}: {exc}", file=sys.stderr)
        manifest.append({"pair": pair, "symbol": symbol, "error": str(exc)})
        continue
      if df is None or df.empty:
        print(f"  {symbol}: sin perpetual / sin datos")
        manifest.append({"pair": pair, "symbol": symbol, "available": False})
        continue
      out_path = OUTDIR / f"{asset}_USDT-funding.feather"
      df.to_feather(out_path)
      manifest.append(
        {
          "pair": pair,
          "symbol": symbol,
          "available": True,
          "rows": len(df),
          "start": str(df["funding_time"].min()),
          "end": str(df["funding_time"].max()),
          "path": str(out_path.relative_to(ROOT)),
        }
      )
  MANIFEST.write_text(
    json.dumps(
      {
        "source": "binance_fapi_v1_fundingRate",
        "note": "Dato de FUTUROS (USDT-perp) usado como senal para operar SPOT. 3 registros/dia (8h).",
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": manifest,
      },
      indent=2,
    ),
    encoding="utf-8",
  )
  ok = sum(1 for x in manifest if x.get("available"))
  print(f"Hecho: {ok}/{len(E2_ASSETS)} perpetuals con funding. Manifest: {MANIFEST}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
