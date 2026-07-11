#!/usr/bin/env python3
"""
Auditoría retroactiva: stoploss materializado en zips de screen/backtest.

Escanea user_data/backtest_results/*.zip y extrae params.stoploss del JSON archivado.
Salida: research/output/screen_stop_audit_20260711.json
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKTEST_DIR = ROOT / "user_data" / "backtest_results"
OUTPUT = ROOT / "research" / "output" / "screen_stop_audit_20260711.json"

# Clase declarada (referencia) — parent chain simplificado
CLASS_STOP = {
  "TrendRider": -0.10,
  "BreakoutVol": -0.10,
  "RegimeSwitcher": -0.10,
  "GridDCA": -0.10,
  "RelativeMomentum": -0.10,
  "XSecMomentum": -0.35,
  "XSecMomentum20M": -0.35,
}


def _params_from_zip(zpath: Path) -> list[dict]:
  rows: list[dict] = []
  try:
    with zipfile.ZipFile(zpath) as zf:
      for name in zf.namelist():
        if not name.endswith(".json") or "_config" in name or "meta" in name:
          continue
        if "backtest-result" in name and name.count("_") < 2:
          continue
        try:
          data = json.loads(zf.read(name))
        except (json.JSONDecodeError, KeyError):
          continue
        if not isinstance(data, dict) or "params" not in data:
          continue
        strategy = data.get("strategy_name") or name.split("_")[-1].replace(".json", "")
        stop = data.get("params", {}).get("stoploss", {}).get("stoploss")
        rows.append(
          {
            "strategy": strategy,
            "stoploss_json": stop,
            "params_file": name,
          }
        )
  except (zipfile.BadZipFile, OSError):
    return []
  return rows


def main() -> int:
  by_strategy: dict[str, list[dict]] = {}
  for zpath in sorted(BACKTEST_DIR.glob("backtest-result-*.zip")):
    for row in _params_from_zip(zpath):
      row["zip"] = zpath.name
      strat = row["strategy"]
      by_strategy.setdefault(strat, []).append(row)

  summary = []
  for strat, rows in sorted(by_strategy.items()):
    stops = {r["stoploss_json"] for r in rows}
    declared = CLASS_STOP.get(strat)
    mismatch = declared is not None and any(s != declared for s in stops if s is not None)
    summary.append(
      {
        "strategy": strat,
        "class_stoploss_declared": declared,
        "stops_in_zips": sorted(stops, key=lambda x: (x is None, x)),
        "zip_count_with_params": len(rows),
        "mismatch_vs_class": mismatch,
        "note": (
          "PARAMS_TEMPLATE forzó -0.1 en variantes con JSON"
          if mismatch and declared == -0.35
          else (
            "coherente con QuantBaseStrategy -0.10"
            if declared == -0.10 and stops == {-0.1}
            else None
          )
        ),
      }
    )

  out = {
    "date": "2026-07-11",
    "failo_vacio": "#10 — PARAMS_TEMPLATE stoploss=-0.1 anulaba clase XSecMomentum -0.35",
    "strategies_audited": summary,
    "screen_discards_1_5": (
      "TrendRider/BreakoutVol/RegimeSwitcher/GridDCA/RelativeMomentum: "
      "stop materializado -0.1 coincide con QuantBaseStrategy; brutos << 0 — irrelevante para veredicto."
    ),
    "xsec_control_zip_reference": "backtest-result-2026-07-10_16-26-23.zip",
    "detail_rows": by_strategy,
  }

  OUTPUT.parent.mkdir(parents=True, exist_ok=True)
  OUTPUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
  print(json.dumps({s["strategy"]: s["stops_in_zips"] for s in summary}, indent=2))
  print(f"JSON: {OUTPUT}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
