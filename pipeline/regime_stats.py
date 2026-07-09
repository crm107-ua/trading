"""Distribución de régimen BTC en una ventana temporal (lectura del reporte OOS)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def regime_distribution_for_timerange(timerange: str) -> dict:
  """
  Porcentaje BULL/BEAR/RANGE en BTC/4h para el timerange OOS.

  Ejecuta en Docker (requiere TA-Lib como el backtest).
  """
  script = f"""
import json
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, "/freqtrade/user_data/strategies")
sys.path.insert(0, "/freqtrade/pipeline")

from _base import QuantBaseStrategy
from pipeline.timerange_split import parse_timerange

timerange = {timerange!r}
start, end = parse_timerange(timerange)
path = Path("/freqtrade/user_data/data/binance/BTC_USDT-4h.feather")
if not path.is_file():
    print(json.dumps({{"error": f"sin datos {{path}}", "timerange": timerange}}))
    raise SystemExit(0)

df = pd.read_feather(path)
labeled = QuantBaseStrategy.add_regime_indicators(df.copy())
dates = pd.to_datetime(labeled["date"], utc=True)
mask = (dates.dt.date >= start) & (dates.dt.date <= end)
sub = labeled.loc[mask, "market_regime"]
if sub.empty:
    print(json.dumps({{"error": "ventana sin velas", "timerange": timerange}}))
    raise SystemExit(0)

counts = sub.value_counts()
total = int(len(sub))
pct = (counts / total * 100).round(1)
out = {{
    "timerange": timerange,
    "start": start.isoformat(),
    "end": end.isoformat(),
    "candles_4h": total,
    "distribution_pct": {{str(k): float(v) for k, v in pct.items()}},
    "counts": {{str(k): int(v) for k, v in counts.items()}},
}}
print(json.dumps(out))
"""
  proc = subprocess.run(
    [
      "docker",
      "compose",
      "run",
      "--rm",
      "--entrypoint",
      "python",
      "freqtrade",
      "-c",
      script,
    ],
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=120,
    check=False,
  )
  output = (proc.stdout or "") + (proc.stderr or "")
  for line in reversed(output.splitlines()):
    line = line.strip()
    if line.startswith("{"):
      try:
        return json.loads(line)
      except json.JSONDecodeError:
        continue
  return {"error": "no se pudo calcular distribución de régimen", "log_tail": output[-500:]}
