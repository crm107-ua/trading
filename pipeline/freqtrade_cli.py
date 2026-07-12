"""Invocación Docker de Freqtrade para backtest e hyperopt."""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKTEST_RESULTS = ROOT / "user_data" / "backtest_results"
LAST_RESULT = BACKTEST_RESULTS / ".last_result.json"

from pipeline.docker_image import (
  FREQTRADE_IMAGE_DIGEST,
  FREQTRADE_IMAGE_PINNED,
  image_digest_from_ref,
  pinned_image_ref,
)
from pipeline.config_hash import resolve_config_paths

# ``hyperopt -j`` forma parte de la secuencia de puntos evaluados (junto a --random-state).
# Hyperopt paralelo falla con el stack config/user_data del lab (ver probe_vanilla_hyperopt_parallel.ps1).
# SampleStrategy + config mínimo sí corre -j 2 en la misma imagen pinneada.
DEFAULT_HYPEROPT_JOB_WORKERS = int(os.environ.get("HYPEROPT_JOB_WORKERS", "1"))


def hyperopt_job_workers() -> int:
  """Workers hyperopt (-j). Todas las semillas de un batch deben usar el mismo valor."""
  return max(1, DEFAULT_HYPEROPT_JOB_WORKERS)


def hyperopt_timeout_seconds(epochs: int) -> int | None:
  """
  Timeout subprocess hyperopt.

  300 epochs × ~1.2 min ≈ 6 h; el default anterior (7200 s) mataba la seed 42 en epoch 299.
  Override: ``HYPEROPT_TIMEOUT_SECONDS`` (0 = sin límite).
  """
  raw = os.environ.get("HYPEROPT_TIMEOUT_SECONDS")
  if raw is not None:
    n = int(raw)
    return None if n <= 0 else n
  # ~2 min/epoch de margen sobre ~1.2 min observado en MeanRevBB -j 1
  return max(14_400, int(epochs * 120))


def docker_runtime_info() -> dict:
  """Metadatos del contenedor para reproducibilidad en report.json."""
  image_ref = pinned_image_ref()
  digest = image_digest_from_ref(image_ref) or FREQTRADE_IMAGE_DIGEST
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
      "import sys; print(sys.version.split()[0])",
    ],
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=60,
    check=False,
  )
  py = (proc.stdout or "").strip().splitlines()[-1] if proc.returncode == 0 else "unknown"
  return {
    "freqtrade_image": image_ref,
    "freqtrade_image_digest": digest,
    "freqtrade_image_pinned_default": FREQTRADE_IMAGE_PINNED,
    "python_version": py,
    "hyperopt_job_workers": hyperopt_job_workers(),
  }


@dataclass
class CommandResult:
  returncode: int
  stdout: str
  stderr: str

  @property
  def output(self) -> str:
    return (self.stdout or "") + (self.stderr or "")


def stop_ephemeral_freqtrade_containers() -> list[str]:
  """
  Detiene contenedores ``*-freqtrade-run-*`` huérfanos (hyperopt/backtest efímeros).

  Cuando el orquestador muere (timeout, crash), ``docker compose run`` puede seguir
  vivo dentro del contenedor efímero.
  """
  proc = subprocess.run(
    ["docker", "ps", "-q", "--filter", "name=freqtrade-run-"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    check=False,
  )
  stopped: list[str] = []
  for cid in (proc.stdout or "").strip().split():
    if not cid:
      continue
    subprocess.run(
      ["docker", "stop", cid],
      capture_output=True,
      text=True,
      encoding="utf-8",
      errors="replace",
      check=False,
    )
    stopped.append(cid)
  return stopped


def _extract_error_tail(output: str, *, max_chars: int = 4000) -> str:
  """Prioriza líneas ERROR/Traceback; si no hay, devuelve el final del log."""
  lines = output.splitlines()
  markers = ("ERROR", "Error", "Traceback", "Exception", "CRITICAL", "fatal", "Timeout")
  err_lines = [ln for ln in lines if any(m in ln for m in markers)]
  if err_lines:
    return "\n".join(err_lines[-50:])
  return output[-max_chars:]


def run_freqtrade(
  args: list[str],
  *,
  timeout: int | None = None,
  env: dict[str, str] | None = None,
) -> CommandResult:
  cmd = ["docker", "compose", "run", "--rm"]
  for key, value in (env or {}).items():
    cmd.extend(["-e", f"{key}={value}"])
  cmd.extend(["freqtrade", *args])
  try:
    proc = subprocess.run(
      cmd,
      cwd=ROOT,
      capture_output=True,
      text=True,
      encoding="utf-8",
      errors="replace",
      timeout=timeout,
      check=False,
    )
    return CommandResult(proc.returncode, proc.stdout or "", proc.stderr or "")
  except subprocess.TimeoutExpired as exc:
    stop_ephemeral_freqtrade_containers()
    out = (exc.stdout or "") + (exc.stderr or "")
    msg = _extract_error_tail(out) if out else ""
    return CommandResult(
      -1,
      exc.stdout or "",
      (exc.stderr or "")
      + "\n[orquestador: timeout subprocess — contenedor efímero detenido]\n"
      + msg,
    )


def base_config_args(extra_config_paths: list[Path] | None = None) -> list[str]:
  args: list[str] = []
  for path in resolve_config_paths(extra_config_paths):
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    args.extend(["--config", rel])
  return args


def format_freqtrade_command(
  subcmd: str,
  strategy: str,
  timerange: str,
  *,
  config_paths: list[Path] | None = None,
  epochs: int | None = None,
  random_state: int | None = None,
  spaces: list[str] | None = None,
  min_trades: int | None = None,
  enable_protections: bool = True,
) -> str:
  """Representación legible del comando docker (dry-plan)."""
  cfg_args: list[str] = []
  for path in config_paths or resolve_config_paths(None):
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    cfg_args.extend(["--config", rel])
  args = [
    "docker compose run --rm freqtrade",
    subcmd,
    *cfg_args,
    "--strategy",
    strategy,
    "--strategy-path",
    "user_data/strategies",
    "--timerange",
    timerange,
  ]
  if subcmd == "hyperopt":
    args.extend(
      [
        "--hyperopt-path",
        "user_data/hyperopts",
        "--spaces",
        *(spaces or ["buy", "sell"]),
        "--epochs",
        str(epochs or 0),
        "--random-state",
        str(random_state or 0),
        "--min-trades",
        str(min_trades or 100),
        "--hyperopt-loss",
        "QuantRobustLoss",
        "--print-json",
        "-j",
        str(hyperopt_job_workers()),
      ]
    )
  elif subcmd == "backtesting":
    args.extend(["--cache", "none", "--export", "trades"])
  if enable_protections:
    args.append("--enable-protections")
  return " ".join(args)


def _read_last_result_name() -> str | None:
  if not LAST_RESULT.is_file():
    return None
  data = json.loads(LAST_RESULT.read_text(encoding="utf-8"))
  return data.get("latest_backtest")


def run_backtest(
  strategy: str,
  timerange: str,
  *,
  enable_protections: bool = True,
  cache: str = "none",
  extra_config_paths: list[Path] | None = None,
) -> tuple[CommandResult, Path | None]:
  before = _read_last_result_name()
  args = [
    "backtesting",
    *base_config_args(extra_config_paths),
    "--strategy",
    strategy,
    "--strategy-path",
    "user_data/strategies",
    "--timerange",
    timerange,
    "--cache",
    cache,
    "--export",
    "trades",
  ]
  if enable_protections:
    args.append("--enable-protections")
  result = run_freqtrade(args, timeout=3600)
  after = _read_last_result_name()
  zip_path: Path | None = None
  if after and after != before:
    candidate = BACKTEST_RESULTS / after
    if candidate.is_file():
      zip_path = candidate
  elif after:
    candidate = BACKTEST_RESULTS / after
    if candidate.is_file() and result.returncode == 0:
      zip_path = candidate
  return result, zip_path


def run_hyperopt(
  strategy: str,
  timerange: str,
  *,
  epochs: int,
  random_state: int,
  enable_protections: bool = True,
  hyperopt_loss: str = "QuantRobustLoss",
  min_trades: int = 100,
  spaces: list[str] | None = None,
  extra_config_paths: list[Path] | None = None,
) -> CommandResult:
  space_args = spaces or ["buy", "sell"]
  args = [
    "hyperopt",
    *base_config_args(extra_config_paths),
    "--hyperopt-path",
    "user_data/hyperopts",
    "--strategy",
    strategy,
    "--strategy-path",
    "user_data/strategies",
    "--timerange",
    timerange,
    "--spaces",
    *space_args,
    "--epochs",
    str(epochs),
    "--random-state",
    str(random_state),
    "--min-trades",
    str(min_trades),
    "--hyperopt-loss",
    hyperopt_loss,
    "--print-json",
    "-j",
    str(hyperopt_job_workers()),
  ]
  if enable_protections:
    args.append("--enable-protections")
  return run_freqtrade(
    args,
    timeout=hyperopt_timeout_seconds(epochs),
    env={"QUANT_ROBUST_MIN_TRADES": str(min_trades)},
  )


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


def parse_backtest_metrics(zip_path: Path, strategy: str) -> dict:
  with zipfile.ZipFile(zip_path) as zf:
    json_name = next(
      n for n in zf.namelist() if n.endswith(".json") and "_config" not in n and "meta" not in n
    )
    payload = json.loads(zf.read(json_name))

  block = payload.get("strategy", {}).get(strategy)
  if not block:
    comp = payload.get("strategy_comparison") or []
    if comp:
      row = next((r for r in comp if r.get("key") == strategy), comp[0])
      return {
        "trades": int(row.get("trades") or 0),
        "profit_total_abs": float(row.get("profit_total_abs") or 0),
        "profit_total": float(row.get("profit_total") or 0),
        "sharpe": float(row.get("sharpe") or 0),
        "sortino": float(row.get("sortino") or 0),
        "max_drawdown_account": float(row.get("max_drawdown_account") or 0),
        "winrate": float(row.get("winrate") or 0),
        "profit_factor": float(row.get("profit_factor") or 0),
      }
    raise KeyError(f"Estrategia {strategy} no encontrada en {zip_path}")

  return {
    "trades": int(block.get("total_trades") or block.get("trades") or 0),
    "profit_total_abs": float(block.get("profit_total_abs") or 0),
    "profit_total": float(block.get("profit_total") or 0),
    "sharpe": float(block.get("sharpe") or 0),
    "sortino": float(block.get("sortino") or 0),
    "max_drawdown_account": float(block.get("max_drawdown_account") or 0),
    "winrate": float(block.get("winrate") or 0),
    "profit_factor": float(block.get("profit_factor") or 0),
  }
