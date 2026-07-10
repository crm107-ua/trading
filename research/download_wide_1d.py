#!/usr/bin/env python3
"""Selecciona pares USDT spot Binance por volumen 24h y descarga 1d (append, sin --erase)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "research" / "wide_universe_manifest.json"
EXCLUDE_SUFFIX = ("UP/USDT", "DOWN/USDT", "BULL/USDT", "BEAR/USDT")
EXCLUDE_BASE = {"USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD", "EUR", "GBP", "AUD", "TRY", "BRL"}


def fetch_top_usdt_pairs(limit: int = 40, min_years: float = 3.0) -> list[str]:
  url = "https://api.binance.com/api/v3/ticker/24hr"
  with urllib.request.urlopen(url, timeout=30) as resp:
    tickers = json.loads(resp.read())
  rows: list[tuple[float, str]] = []
  for t in tickers:
    sym = t.get("symbol", "")
    if not sym.endswith("USDT"):
      continue
    base = sym[:-4]
    if base in EXCLUDE_BASE:
      continue
    pair = f"{base}/USDT"
    if any(pair.endswith(s) for s in EXCLUDE_SUFFIX):
      continue
    qv = float(t.get("quoteVolume") or 0)
    rows.append((qv, pair))
  rows.sort(reverse=True)
  return [p for _, p in rows[:limit]]


def download_batch(pairs: list[str], timerange: str = "20210101-") -> None:
  if not pairs:
    return
  cmd = [
    "docker",
    "compose",
    "run",
    "--rm",
    "--no-deps",
    "freqtrade",
    "download-data",
    "--config",
    "user_data/config/base.json",
    "--config",
    "user_data/config/backtest.json",
    "--exchange",
    "binance",
    "--timeframes",
    "1d",
    "--timerange",
    timerange,
    "--pairs",
    *pairs,
  ]
  subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
  limit = int(sys.argv[1]) if len(sys.argv) > 1 else 35
  batch = int(sys.argv[2]) if len(sys.argv) > 2 else 8
  pairs = fetch_top_usdt_pairs(limit=limit)
  MANIFEST.parent.mkdir(parents=True, exist_ok=True)
  MANIFEST.write_text(json.dumps({"pairs": pairs, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}, indent=2), encoding="utf-8")
  print(f"Top {len(pairs)} pares USDT → {MANIFEST}")
  for i in range(0, len(pairs), batch):
    chunk = pairs[i : i + batch]
    print(f"Descarga lote {i // batch + 1}: {chunk}")
    download_batch(chunk)
    time.sleep(2)
  print("Hecho. Verificar: python -c \"from research.xsec_lab import list_available_1d_pairs; print(len(list_available_1d_pairs()))\"")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
