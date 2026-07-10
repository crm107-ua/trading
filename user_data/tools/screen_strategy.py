#!/usr/bin/env python3
"""
Screen pre-validación — backtests secuenciales (defaults + variantes JSON) y veredicto.

Uso (host):
  python user_data/tools/screen_strategy.py RelativeMomentum --timerange 20210101-
  python user_data/tools/screen_strategy.py TrendRider --skip-defaults --prior-report user_data/validation_reports/screen/TrendRider/20260710_101302/screen_report.json

Dentro de Docker:
  docker compose run --rm --no-deps --name ft-screen-once --entrypoint python freqtrade \\
    user_data/tools/screen_strategy.py RelativeMomentum --inside-docker
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import zipfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from pipeline.params_manager import (  # noqa: E402
  clear_strategy_params,
  install_strategy_params,
  parse_loaded_params_from_log,
  strategy_params_path,
)

REPORTS = ROOT / "user_data" / "validation_reports" / "screen"
STRATEGIES_DIR = ROOT / "user_data" / "strategies"
BACKTEST_RESULTS = ROOT / "user_data" / "backtest_results"
LAST_RESULT = BACKTEST_RESULTS / ".last_result.json"
HYPEROPT_LAST_RESULT = ROOT / "user_data" / "hyperopt_results" / ".last_result.json"
VARIANTS_DIR = ROOT / "user_data" / "fixtures" / "screen_variants"
DEFAULT_CONFIGS = [
  ROOT / "user_data/config/base.json",
  ROOT / "user_data/config/backtest.json",
]

HYPEROPT_PARAM_RE = re.compile(
  r"^\s*(\w+)\s*=\s*(?:IntParameter|DecimalParameter)\([^)]*default=([^,\)]+)[^)]*space=[\"'](buy|sell)[\"']",
  re.MULTILINE,
)

# Atributos de clase que las variantes del screen pueden pedir pero Freqtrade no carga vía .json.
NON_JSON_LOADABLE_PARAMS = frozenset({"atr_stop_multiplier"})

PARAMS_TEMPLATE = {
  "roi": {"0": 100},
  "stoploss": {"stoploss": -0.1},
  "trailing": {
    "trailing_stop": False,
    "trailing_stop_positive": None,
    "trailing_stop_positive_offset": 0.0,
    "trailing_only_offset_is_reached": False,
  },
  "max_open_trades": {"max_open_trades": 4},
}

HYPEROPT_RISK_EPOCH_THRESHOLD = 280
HYPEROPT_TARGET_EPOCHS = 300


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
  params_verified: bool = True
  verify_issues: list[str] = field(default_factory=list)


@dataclass
class ScreenVerdict:
  verdict: str
  reasons: list[str]


class ScreenAbortError(RuntimeError):
  """Screen abortado: verificación de params o variantes gemelas."""


def _parse_hyperopt_registry(strategy: str) -> dict[str, tuple[str, object]]:
  """``{param_name: (space, default_value)}`` desde el .py de la estrategia."""
  path = STRATEGIES_DIR / f"{strategy}.py"
  if not path.is_file():
    raise FileNotFoundError(f"estrategia no encontrada: {path}")
  text = path.read_text(encoding="utf-8")
  registry: dict[str, tuple[str, object]] = {}
  for match in HYPEROPT_PARAM_RE.finditer(text):
    name, default_raw, space = match.group(1), match.group(2).strip(), match.group(3)
    try:
      default_val: object = json.loads(default_raw)
    except json.JSONDecodeError:
      default_val = default_raw.strip("\"'")
    registry[name] = (space, default_val)
  return registry


def build_variant_params_export(strategy: str, overrides: dict) -> dict | None:
  """
  Construye el JSON que Freqtrade carga desde ``user_data/strategies/<Estrategia>.json``.

  Freqtrade exige el bloque buy/sell **completo**; overrides parciales se fusionan con defaults
  del IntParameter/DecimalParameter en el .py de la estrategia.
  """
  if not overrides:
    return None

  non_loadable = set(overrides) & NON_JSON_LOADABLE_PARAMS
  if non_loadable:
    raise ScreenAbortError(
      f"variante incluye parámetros no cargables vía <Estrategia>.json: {sorted(non_loadable)}"
    )

  registry = _parse_hyperopt_registry(strategy)
  unknown = set(overrides) - set(registry)
  if unknown:
    raise ScreenAbortError(f"parámetros desconocidos para {strategy}: {sorted(unknown)}")

  buy_block: dict[str, object] = {}
  sell_block: dict[str, object] = {}
  for name, (space, default_val) in registry.items():
    value = overrides.get(name, default_val)
    if space == "buy":
      buy_block[name] = value
    else:
      sell_block[name] = value

  params = dict(PARAMS_TEMPLATE)
  if buy_block:
    params["buy"] = buy_block
  if sell_block:
    params["sell"] = sell_block

  return {
    "strategy_name": strategy,
    "params": params,
    "ft_stratparam_v": 1,
  }


def write_variant_params_file(strategy: str, overrides: dict, dest: Path) -> Path | None:
  """Escribe export de variante; ``None`` si overrides vacíos (defaults de clase)."""
  payload = build_variant_params_export(strategy, overrides)
  if payload is None:
    return None
  dest.parent.mkdir(parents=True, exist_ok=True)
  dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
  return dest


def assert_screen_allowed(strategy: str) -> None:
  """Rechaza screen si el lock activo nombra la estrategia (MeanRevBB vetado durante validación)."""
  try:
    from pipeline.run_lock import read_lock
  except Exception:
    return

  lock = read_lock()
  if lock is not None and lock.strategy == strategy:
    raise ScreenAbortError(
      f"screen de {strategy} vetado: validación activa (run_id={lock.run_id}, pid={lock.pid})"
    )


def _hyperopt_epochs_in_progress() -> int | None:
  try:
    from pipeline.hyperopt_resume import count_fthypt_epochs, list_strategy_fthypt_files
    from pipeline.run_lock import read_lock
  except Exception:
    return None

  lock = read_lock()
  if lock is None:
    return None
  files = list_strategy_fthypt_files(lock.strategy)
  if not files:
    return None
  return count_fthypt_epochs(files[0])


def wait_if_hyperopt_risk_window(
  *,
  threshold: int = HYPEROPT_RISK_EPOCH_THRESHOLD,
  target_epochs: int = HYPEROPT_TARGET_EPOCHS,
  poll_seconds: int = 60,
) -> None:
  """Espera si hyperopt del lock activo supera ~280/300 epochs (estado compartido)."""
  while True:
    done = _hyperopt_epochs_in_progress()
    if done is None or done < threshold:
      return
    print(
      f"Esperando fin de ventana hyperopt ({done}/{target_epochs} epochs)…",
      file=sys.stderr,
    )
    time.sleep(poll_seconds)


def verify_defaults_loaded(log_output: str) -> tuple[bool, list[str]]:
  issues: list[str] = []
  if "Loading parameters from file" in log_output:
    issues.append("defaults esperados pero Freqtrade cargó archivo de params")
  if "Strategy Parameter(default)" not in log_output and "using default values" not in log_output:
    issues.append("log no confirma parámetros default de estrategia")
  return len(issues) == 0, issues


def verify_variant_params_applied(
  strategy: str,
  requested: dict,
  params_file: Path | None,
  log_output: str,
) -> tuple[bool, list[str]]:
  if not requested:
    return verify_defaults_loaded(log_output)

  issues: list[str] = []
  non_loadable = set(requested) & NON_JSON_LOADABLE_PARAMS
  if non_loadable:
    issues.append(f"parámetros no cargables: {sorted(non_loadable)}")

  if params_file is None or not params_file.is_file():
    issues.append("variante con overrides pero sin archivo de params de verificación")

  loaded = parse_loaded_params_from_log(log_output)
  if not loaded:
    issues.append("log sin Strategy Parameter — no auditable qué cargó Freqtrade")
    return False, issues

  if params_file is not None and "Loading parameters from file" not in log_output:
    issues.append("log no confirma carga de archivo de params")

  for key, exp_val in requested.items():
    if key in NON_JSON_LOADABLE_PARAMS:
      continue
    candidates = {key, key.replace("buy_", ""), key.replace("sell_", "")}
    found = None
    for cand in candidates:
      if cand in loaded:
        found = loaded[cand]
        break
    if found is None:
      issues.append(f"override solicitado no aparece en log: {key}")
    elif str(found) != str(exp_val):
      issues.append(f"override {key}: solicitado {exp_val}, log={found}")

  if "Strategy Parameter(default)" in log_output:
    for key in requested:
      if key in NON_JSON_LOADABLE_PARAMS:
        continue
      # Si el log marca default para un param que pedimos override, falla.
      for cand in (key, key.replace("buy_", ""), key.replace("sell_", "")):
        if f"Strategy Parameter(default): {cand}" in log_output:
          issues.append(f"override {key} cargó como default en log")
          break

  return len(issues) == 0, issues


def metrics_signature(metrics: VariantMetrics) -> tuple:
  return (
    metrics.trades,
    metrics.profit_net_abs,
    metrics.profit_gross_abs,
    metrics.total_fees_abs,
    metrics.sharpe,
    metrics.max_drawdown_account,
  )


def detect_identical_variants(metrics: list[VariantMetrics]) -> tuple[bool, list[str]]:
  """True si dos o más variantes comparten métricas idénticas (bit a bit)."""
  buckets: dict[tuple, list[str]] = {}
  for m in metrics:
    sig = metrics_signature(m)
    buckets.setdefault(sig, []).append(m.name)
  twins = [names for names in buckets.values() if len(names) >= 2]
  if not twins:
    return False, []
  details = [f"{', '.join(names)} → misma firma" for names in twins]
  return True, details


def _load_variants(strategy: str, variants_path: Path | None) -> list[dict]:
  path = variants_path or (VARIANTS_DIR / f"{strategy}.json")
  if not path.is_file():
    return [{"name": "defaults", "strategy_parameters": {}}]
  raw = path.read_text(encoding="utf-8")
  lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")]
  payload = json.loads("\n".join(lines))
  return list(payload.get("variants") or [{"name": "defaults", "strategy_parameters": {}}])


def load_prior_defaults(prior_report: Path) -> VariantMetrics:
  data = json.loads(prior_report.read_text(encoding="utf-8"))
  row = next((v for v in data.get("variants", []) if v.get("name") == "defaults"), None)
  if row is None:
    raise ScreenAbortError(f"sin fila defaults en reporte previo: {prior_report}")
  return VariantMetrics(
    name="defaults",
    strategy_parameters=dict(row.get("strategy_parameters") or {}),
    zip_path=str(row.get("zip_path") or ""),
    trades=int(row["trades"]),
    profit_net_abs=float(row["profit_net_abs"]),
    profit_gross_abs=float(row["profit_gross_abs"]),
    total_fees_abs=float(row["total_fees_abs"]),
    sharpe=float(row.get("sharpe") or 0),
    max_drawdown_account=float(row.get("max_drawdown_account") or 0),
    friction_ratio=row.get("friction_ratio"),
    params_verified=bool(row.get("params_verified", True)),
    verify_issues=list(row.get("verify_issues") or []),
  )


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


@contextmanager
def _pipeline_mutable_state_guard(strategy: str):
  """
  Snapshot/restore de punteros compartidos con run_validation (near-miss .last_result.json)
  y de ``<Estrategia>.json`` que el screen escribe por variante.
  """
  guarded = (LAST_RESULT, HYPEROPT_LAST_RESULT, strategy_params_path(strategy))
  snapshots: dict[Path, bytes | None] = {}
  for path in guarded:
    snapshots[path] = path.read_bytes() if path.is_file() else None
  try:
    yield
  finally:
    for path, content in snapshots.items():
      path.parent.mkdir(parents=True, exist_ok=True)
      if content is None:
        path.unlink(missing_ok=True)
      else:
        path.write_bytes(content)


def _docker_config_path(path: Path) -> str:
  rel = path.relative_to(ROOT).as_posix()
  return f"/freqtrade/{rel}"


def _install_variant_params(
  strategy: str,
  overrides: dict,
  staging_dir: Path,
  *,
  label: str,
) -> Path | None:
  if not overrides:
    clear_strategy_params(strategy)
    return None
  staging = staging_dir / f"{strategy}_{label}_params.json"
  write_variant_params_file(strategy, overrides, staging)
  install_strategy_params(strategy, staging)
  return staging


def _run_docker_backtest(
  strategy: str,
  timerange: str,
  *,
  datadir: str,
  extra_configs: list[Path],
  overrides: dict,
  staging_dir: Path,
  container_name: str,
  variant_label: str,
) -> tuple[Path, str, Path | None]:
  wait_if_hyperopt_risk_window()

  config_args: list[str] = []
  for cfg in DEFAULT_CONFIGS + extra_configs:
    config_args.extend(["--config", _docker_config_path(cfg)])

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

  verify_file: Path | None = None
  log_output = ""
  z: Path | None = None

  with _pipeline_mutable_state_guard(strategy):
    verify_file = _install_variant_params(strategy, overrides, staging_dir, label=variant_label)
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log_output = f"{proc.stdout}\n{proc.stderr}"
    if proc.returncode != 0:
      raise RuntimeError(
        f"backtest falló ({strategy}): exit={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
      )
    z = latest_backtest_zip()

  if z is None:
    raise FileNotFoundError("sin zip de backtest tras screen")
  return z, log_output, verify_file


def run_screen(
  strategy: str,
  *,
  timerange: str,
  variants_file: Path | None,
  datadir: str,
  extra_configs: list[Path],
  dry_run: bool = False,
  skip_defaults: bool = False,
  prior_report: Path | None = None,
) -> dict:
  assert_screen_allowed(strategy)

  run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
  out_dir = REPORTS / strategy / run_id
  out_dir.mkdir(parents=True, exist_ok=True)

  variants = _load_variants(strategy, variants_file)
  if skip_defaults:
    variants = [v for v in variants if str(v.get("name") or "") != "defaults"]

  results: list[VariantMetrics] = []
  prior_defaults_path: str | None = None

  if skip_defaults:
    if prior_report is None:
      raise ScreenAbortError("--skip-defaults requiere --prior-report")
    prior_defaults_path = str(prior_report)
    results.append(load_prior_defaults(prior_report))

  for i, variant in enumerate(variants):
    name = str(variant.get("name") or f"variant_{i}")
    params = dict(variant.get("strategy_parameters") or {})
    if dry_run:
      continue

    container = f"ft-screen-{strategy.lower()}-{run_id}-{i}"
    zip_path, log_output, verify_file = _run_docker_backtest(
      strategy,
      timerange,
      datadir=datadir,
      extra_configs=extra_configs,
      overrides=params,
      staging_dir=out_dir,
      container_name=container,
      variant_label=name,
    )
    metrics = parse_backtest_zip(zip_path, strategy)
    metrics.name = name
    metrics.strategy_parameters = params

    verified, issues = verify_variant_params_applied(strategy, params, verify_file, log_output)
    metrics.params_verified = verified
    metrics.verify_issues = issues
    if not verified:
      raise ScreenAbortError(
        f"params no verificados para variante '{name}': {'; '.join(issues)}"
      )
    results.append(metrics)

  invalid: str | None = None
  verdict: ScreenVerdict | None = None
  reasons: list[str] = []

  if results:
    twins, twin_details = detect_identical_variants(results)
    if twins:
      invalid = "variants_identical"
      reasons = twin_details
    elif all(m.params_verified for m in results):
      verdict = evaluate_screen(results)
      reasons = verdict.reasons
    else:
      invalid = "params_unverified"
      reasons = ["alguna variante sin params_verified"]

  report = {
    "strategy": strategy,
    "run_id": run_id,
    "timerange": timerange,
    "datadir": datadir,
    "variants": [asdict(m) for m in results],
    "verdict": verdict.verdict if verdict else None,
    "reasons": reasons,
    "invalid": invalid,
    "params_verified_all": all(m.params_verified for m in results) if results else False,
    "prior_defaults_from": prior_defaults_path,
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
  parser.add_argument("--skip-defaults", action="store_true", help="Omitir variante defaults (re-screen)")
  parser.add_argument("--prior-report", type=Path, default=None, help="Reporte con defaults de ayer")
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

  try:
    report = run_screen(
      args.strategy,
      timerange=args.timerange,
      variants_file=args.variants_file,
      datadir=datadir,
      extra_configs=extra,
      skip_defaults=args.skip_defaults,
      prior_report=args.prior_report,
    )
  except ScreenAbortError as exc:
    print(f"SCREEN ABORTADO: {exc}", file=sys.stderr)
    return 2

  print(json.dumps(report, indent=2))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
