#!/usr/bin/env python3
"""
Screen pre-validación — backtests secuenciales (defaults + variantes JSON) y veredicto.

Uso (host):
  python user_data/tools/screen_strategy.py RelativeMomentum --timerange 20210101-

Dentro de Docker:
  docker compose run --rm --no-deps --name ft-screen-once --entrypoint python freqtrade \\
    user_data/tools/screen_strategy.py RelativeMomentum --inside-docker
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "user_data" / "validation_reports" / "screen"
BACKTEST_RESULTS = ROOT / "user_data" / "backtest_results"
LAST_RESULT = BACKTEST_RESULTS / ".last_result.json"
VARIANTS_DIR = ROOT / "user_data" / "fixtures" / "screen_variants"
DEFAULT_CONFIGS = [
  ROOT / "user_data/config/base.json",
  ROOT / "user_data/config/backtest.json",
]


@dataclass
class VariantMetrics:
  name: str
  strategy_parameters: dict
  zip_path: str
  trades: int
  profit_net_abs: float
  profit_gross_abs: float
  total_fees_abs: float
  sharpe: float
  max_drawdown_account: float
  friction_ratio: float | None


@dataclass
class ScreenVerdict:
  verdict: str
  reasons: list[str]


def _load_variants(strategy: str, variants_path: Path | None) -> list[dict]:
  path = variants_path or (VARIANTS_DIR / f"{strategy}.json")
  if not path.is_file():
    return [{"name": "defaults", "strategy_parameters": {}}]
  payload = json.loads(path.read_text(encoding="utf-8"))
  return list(payload.get("variants") or [{"name": "defaults", "strategy_parameters": {}}])


def _strategy_block(zip_path: Path, strategy: str) -> dict:
  with zipfile.ZipFile(zip_path) as zf:
    json_name = next(
      n for n in zf.namelist() if n.endswith(".json") and "_config" not in n and "meta" not in n
    )
    payload = json.loads(zf.read(json_name))
  block = payload.get("strategy", {}).get(strategy)
  if block:
    return block
  comp = payload.get("strategy_comparison") or []
  row = next((r for r in comp if r.get("key") == strategy), None)
  if row:
    return row
  raise KeyError(f"Estrategia {strategy} no encontrada en {zip_path}")


def _total_fees_from_trades(trades: list[dict]) -> float:
  total = 0.0
  for t in trades:
    for key in ("fee", "fee_open", "fee_close"):
      val = t.get(key)
      if val is not None:
        total += abs(float(val))
  return total


def parse_backtest_zip(zip_path: Path, strategy: str) -> VariantMetrics:
  block = _strategy_block(zip_path, strategy)
  trades = list(block.get("trades") or [])
  profit_net = float(block.get("profit_total_abs") or 0)
  fees = _total_fees_from_trades(trades)
  gross = profit_net + fees
  friction = (fees / gross) if gross > 0 else None
  return VariantMetrics(
    name="",
    strategy_parameters={},
    zip_path=str(zip_path),
    trades=int(block.get("total_trades") or block.get("trades") or len(trades)),
    profit_net_abs=profit_net,
    profit_gross_abs=gross,
    total_fees_abs=fees,
    sharpe=float(block.get("sharpe") or 0),
    max_drawdown_account=float(block.get("max_drawdown_account") or 0),
    friction_ratio=friction,
  )


def evaluate_screen(metrics: list[VariantMetrics]) -> ScreenVerdict:
  reasons: list[str] = []
  passed: list[str] = []
  any_gross_positive = False

  for m in metrics:
    if m.profit_gross_abs > 0:
      any_gross_positive = True
      ok_trades = m.trades >= 30
      ok_friction = m.total_fees_abs < 0.5 * m.profit_gross_abs
      if ok_trades and ok_friction:
        passed.append(m.name)
      else:
        if not ok_trades:
          reasons.append(f"{m.name}: trades {m.trades} < 30")
        if not ok_friction:
          reasons.append(
            f"{m.name}: comisiones {m.total_fees_abs:.2f} >= 50% bruto {m.profit_gross_abs:.2f}"
          )

  if passed:
    return ScreenVerdict(
      verdict="PASA",
      reasons=[f"variantes que pasan: {', '.join(passed)}"],
    )
  if any_gross_positive:
    return ScreenVerdict(verdict="ZONA_GRIS", reasons=reasons or ["bruto>0 sin cumplir fricción/trades"])
  return ScreenVerdict(verdict="DESCARTADA", reasons=["ninguna variante con PnL bruto > 0"])


def latest_backtest_zip() -> Path | None:
  if LAST_RESULT.is_file():
    data = json.loads(LAST_RESULT.read_text(encoding="utf-8"))
    name = data.get("latest_backtest")
    if name:
      path = BACKTEST_RESULTS / name
      if path.is_file():
        return path
  zips = sorted(BACKTEST_RESULTS.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime)
  return zips[-1] if zips else None


def _run_docker_backtest(
  strategy: str,
  timerange: str,
  *,
  datadir: str,
  extra_configs: list[Path],
  strategy_parameters: dict,
  container_name: str,
) -> Path:
  config_args: list[str] = []
  for cfg in DEFAULT_CONFIGS + extra_configs:
    config_args.extend(["--config", str(cfg).replace("\\", "/")])

  cmd = [
    "docker",
    "compose",
    "run",
    "--rm",
    "--no-deps",
    "--name",
    container_name,
    "freqtrade",
    "backtesting",
    *config_args,
    "--datadir",
    datadir,
    "--strategy",
    strategy,
    "--strategy-path",
    "user_data/strategies",
    "--timerange",
    timerange,
    "--cache",
    "none",
  ]
  if strategy_parameters:
    params_path = ROOT / "user_data" / "validation_reports" / "screen" / ".tmp_params.json"
    params_path.parent.mkdir(parents=True, exist_ok=True)
    params_path.write_text(json.dumps({"strategy_parameters": strategy_parameters}), encoding="utf-8")
    cmd.extend(["--config", str(params_path).replace("\\", "/")])

  proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
  if proc.returncode != 0:
    raise RuntimeError(
      f"backtest falló ({strategy}): exit={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    )
  z = latest_backtest_zip()
  if z is None:
    raise FileNotFoundError("sin zip de backtest tras screen")
  return z


def run_screen(
  strategy: str,
  *,
  timerange: str,
  variants_file: Path | None,
  datadir: str,
  extra_configs: list[Path],
  dry_run: bool = False,
) -> dict:
  run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
  out_dir = REPORTS / strategy / run_id
  out_dir.mkdir(parents=True, exist_ok=True)

  variants = _load_variants(strategy, variants_file)
  results: list[VariantMetrics] = []

  for i, variant in enumerate(variants):
    name = str(variant.get("name") or f"variant_{i}")
    params = dict(variant.get("strategy_parameters") or {})
    if dry_run:
      continue
    container = f"ft-screen-{strategy.lower()}-{i}"
    zip_path = _run_docker_backtest(
      strategy,
      timerange,
      datadir=datadir,
      extra_configs=extra_configs,
      strategy_parameters=params,
      container_name=container,
    )
    metrics = parse_backtest_zip(zip_path, strategy)
    metrics.name = name
    metrics.strategy_parameters = params
    results.append(metrics)

  verdict = evaluate_screen(results) if results else ScreenVerdict("ZONA_GRIS", ["dry_run sin backtests"])
  report = {
    "strategy": strategy,
    "run_id": run_id,
    "timerange": timerange,
    "datadir": datadir,
    "variants": [asdict(m) for m in results],
    "verdict": verdict.verdict,
    "reasons": verdict.reasons,
    "protocol": "docs/screen_protocol.md",
  }
  out_path = out_dir / "screen_report.json"
  if not dry_run:
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
  return report


def main() -> int:
  parser = argparse.ArgumentParser(description="Screen pre-validación")
  parser.add_argument("strategy", help="Nombre de estrategia")
  parser.add_argument("--timerange", default="20210101-", help="Ventana de backtest")
  parser.add_argument("--variants-file", type=Path, default=None)
  parser.add_argument(
    "--datadir",
    default="user_data/data/binance",
    help="Datadir host (se monta como /freqtrade/... en Docker)",
  )
  parser.add_argument(
    "--fixtures",
    action="store_true",
    help="Usar fixtures RelativeMomentum y config dedicada",
  )
  parser.add_argument("--parse-zip", type=Path, help="Solo parsear zip existente (sin backtests)")
  parser.add_argument("--inside-docker", action="store_true", help=argparse.SUPPRESS)
  args = parser.parse_args()

  if args.parse_zip:
    m = parse_backtest_zip(args.parse_zip, args.strategy)
    print(json.dumps(asdict(m), indent=2))
    return 0

  extra: list[Path] = []
  datadir = f"/freqtrade/{args.datadir.replace(chr(92), '/')}"
  if args.fixtures:
    extra.append(ROOT / "user_data/config/backtest_relative_momentum_fixtures.json")
    datadir = "/freqtrade/tests/fixtures/data_relative_momentum/binance"

  try:
    from pipeline.run_lock import read_lock

    if read_lock() is not None:
      print(
        "AVISO: validación activa — screen lanzará backtests secuenciales (uno a uno).",
        file=sys.stderr,
      )
  except Exception:
    pass

  report = run_screen(
    args.strategy,
    timerange=args.timerange,
    variants_file=args.variants_file,
    datadir=datadir,
    extra_configs=extra,
  )
  print(json.dumps(report, indent=2))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
