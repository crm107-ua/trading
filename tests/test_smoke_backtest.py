"""Tests unitarios y de integración — Fase 1: smoke backtest."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CONFIGS = [
  "user_data/config/base.json",
  "user_data/config/backtest.json",
  "user_data/config/backtest_fixtures.json",
]

# Segmentos deliberados en tests/fixtures/generate_data.py
BULL_TIMERANGE = "20240115-20240228"
RANGE_TIMERANGE = "20240215-20240318"
DCA_TIMERANGE = "20240120-20240128"
DEFAULT_TIMERANGE = "20240101-20240320"


def _parse_trade_count(output: str, strategy: str) -> int | None:
  import re

  # Freqtrade 2026 usa │ (U+2502); versiones previas usaban ┃ (U+2503)
  patterns = [
    rf"[│┃]\s*{re.escape(strategy)}\s+[│┃]\s+(\d+)",
    rf"\|\s*{re.escape(strategy)}\s+\|\s+(\d+)",
  ]
  for pattern in patterns:
    m = re.search(pattern, output)
    if m:
      return int(m.group(1))
  return None


def _config_flags(configs: list[str] | None = None, *, fixtures: bool = True) -> list[str]:
  """Flags para comandos ``freqtrade`` CLI (backtest, recursive-analysis, etc.)."""
  flags: list[str] = []
  for cfg in configs or FIXTURE_CONFIGS:
    flags.extend(["--config", cfg])
  if fixtures:
    flags.extend(["--datadir", "/freqtrade/user_data/fixtures/data/binance"])
  return flags


def _tool_config_flags(configs: list[str] | None = None) -> list[str]:
  """
  Flags para ``user_data/tools/*.py`` programáticos.

  Esas herramientas fijan el datadir de fixtures vía ``fixture_config``;
  pasar ``--datadir`` por CLI rompe el contrato (ver ``backtest_all.ps1``).
  """
  flags: list[str] = []
  for cfg in configs or FIXTURE_CONFIGS:
    flags.extend(["--config", cfg])
  return flags


def _run_backtest(
  strategy: str,
  timerange: str,
  *,
  extra_configs: list[str] | None = None,
  fixtures: bool = True,
) -> subprocess.CompletedProcess[str]:
  cmd = [
    "docker",
    "compose",
    "run",
    "--rm",
    "freqtrade",
    "backtesting",
    *_config_flags(extra_configs, fixtures=fixtures),
    "--strategy",
    strategy,
    "--timerange",
    timerange,
    "--cache",
    "none",
  ]
  return subprocess.run(
    cmd,
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=300,
    check=False,
  )


def _docker_available() -> bool:
  try:
    result = subprocess.run(
      ["docker", "info"],
      capture_output=True,
      timeout=30,
      check=False,
    )
    return result.returncode == 0
  except (FileNotFoundError, subprocess.TimeoutExpired):
    return False


def _env_file_exists() -> bool:
  return (ROOT / ".env").exists()


@pytest.fixture(scope="module")
def fixtures_datadir() -> Path:
  """Fixtures en tests/fixtures/data — nunca copiar a user_data/data."""
  path = ROOT / "tests" / "fixtures" / "data" / "binance"
  assert path.exists(), "Ejecutar scripts/regenerate_fixtures.ps1"
  return path


@pytest.mark.integration
@pytest.mark.parametrize("strategy", ["TrendRider", "MeanRevBB", "BreakoutVol"])
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env (copiar desde .env.example)")
def test_btc_regime_not_constant_on_fixtures(
  fixtures_datadir: Path, strategy: str
) -> None:
  """btc_market_regime debe variar (BULL+RANGE); detecta informative roto."""
  cmd = [
    "docker",
    "compose",
    "run",
    "--rm",
    "--entrypoint",
    "python",
    "freqtrade",
    "user_data/tools/regime_variety_check.py",
    "--strategy",
    strategy,
    "--timerange",
    DEFAULT_TIMERANGE,
    *_tool_config_flags(),
  ]
  result = subprocess.run(
    cmd,
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=300,
    check=False,
  )
  output = (result.stdout or "") + (result.stderr or "")
  assert result.returncode == 0, (
    f"Regime variety falló para {strategy}\n{output[-3000:]}"
  )
  assert "OK: régimen variado" in output


@pytest.mark.integration
@pytest.mark.parametrize(
  "strategy",
  ["SmokeTestStrategy", "TrendRider", "MeanRevBB", "BreakoutVol"],
)
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env (copiar desde .env.example)")
def test_recursive_analysis_clean(fixtures_datadir: Path, strategy: str) -> None:
  """Indicadores estables con warmup correcto (sin sesgo en informative)."""
  cmd = [
    "docker",
    "compose",
    "run",
    "--rm",
    "freqtrade",
    "recursive-analysis",
    *_config_flags(),
    "--strategy",
    strategy,
    "--strategy-path",
    "user_data/strategies",
    "--timerange",
    DEFAULT_TIMERANGE,
    "--startup-candle",
    "199",
    "499",
    "999",
    "1999",
  ]
  result = subprocess.run(
    cmd,
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=300,
    check=False,
  )
  output = (result.stdout or "") + (result.stderr or "")
  assert result.returncode == 0, (
    f"Recursive-analysis falló para {strategy} (code={result.returncode})\n{output[-4000:]}"
  )
  lowered = output.lower()
  assert "no lookahead bias on indicators found" in lowered


@pytest.mark.integration
@pytest.mark.parametrize(
  "strategy",
  ["SmokeTestStrategy", "TrendRider", "MeanRevBB", "BreakoutVol"],
)
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env (copiar desde .env.example)")
def test_signal_truncation_clean(fixtures_datadir: Path, strategy: str) -> None:
  """Señales enter_long/exit_long invariantes al truncar datos futuros."""
  cmd = [
    "docker",
    "compose",
    "run",
    "--rm",
    "--entrypoint",
    "python",
    "freqtrade",
    "user_data/tools/signal_truncation_check.py",
    "--strategy",
    strategy,
    "--timerange",
    DEFAULT_TIMERANGE,
    *_tool_config_flags(),
  ]
  result = subprocess.run(
    cmd,
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=600,
    check=False,
  )
  output = (result.stdout or "") + (result.stderr or "")
  assert result.returncode == 0, (
    f"Signal truncation falló para {strategy} (code={result.returncode})\n{output[-4000:]}"
  )
  assert "OK: señales idénticas" in output


@pytest.mark.integration
@pytest.mark.parametrize(
  "strategy",
  ["SmokeTestStrategy", "TrendRider", "MeanRevBB", "BreakoutVol"],
)
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env (copiar desde .env.example)")
def test_lookahead_analysis_advisory(fixtures_datadir: Path, strategy: str) -> None:
  """
  Lookahead trade-based (advisory): no bloquea CI; ver docs/OPERATIONS.md.
  """
  cmd = [
    "docker",
    "compose",
    "run",
    "--rm",
    "freqtrade",
    "lookahead-analysis",
    *_config_flags(),
    "--config",
    "user_data/config/lookahead.json",
    "--strategy",
    strategy,
    "--strategy-path",
    "user_data/strategies",
    "--timerange",
    DEFAULT_TIMERANGE,
  ]
  result = subprocess.run(
    cmd,
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=300,
    check=False,
  )
  output = (result.stdout or "") + (result.stderr or "")
  assert result.returncode == 0, (
    f"Lookahead falló para {strategy} (code={result.returncode})\n{output[-4000:]}"
  )
  lowered = output.lower()
  assert "configuration error" not in lowered
  # Advisory: solo registramos; no fallamos por bias detected
  if "bias detected" in lowered:
    return
  if "too few trades" in lowered or "cancelling" in lowered:
    return
  assert result.returncode == 0


@pytest.mark.integration
@pytest.mark.parametrize(
  "strategy",
  ["SmokeTestStrategy", "TrendRider", "MeanRevBB", "BreakoutVol"],
)
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env (copiar desde .env.example)")
def test_smoke_backtest_runs(fixtures_datadir: Path, strategy: str) -> None:
  """
  Backtest smoke: termina sin errores sobre el timerange completo de fixtures.
  """
  result = _run_backtest(strategy, DEFAULT_TIMERANGE)
  assert result.returncode == 0, (
    f"Backtest falló (code={result.returncode})\n"
    f"STDOUT:\n{(result.stdout or '')[-4000:]}\nSTDERR:\n{(result.stderr or '')[-4000:]}"
  )
  output = (result.stdout or "") + (result.stderr or "")
  assert "STRATEGY SUMMARY" in output or "Backtested" in output


@pytest.mark.integration
@pytest.mark.parametrize("strategy", ["TrendRider", "BreakoutVol"])
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env (copiar desde .env.example)")
def test_bull_strategies_execute_trades(
  fixtures_datadir: Path, strategy: str
) -> None:
  """Ejercita entrada→trailing→salida en ventana BULL sintética (motor Freqtrade)."""
  result = _run_backtest(strategy, BULL_TIMERANGE)
  output = (result.stdout or "") + (result.stderr or "")
  assert result.returncode == 0, f"Backtest BULL falló para {strategy}\n{output[-3000:]}"
  trades = _parse_trade_count(output, strategy)
  assert trades is not None, f"No se pudo parsear trades para {strategy}\n{output[-2000:]}"
  assert trades > 0, (
    f"{strategy} ejecutó 0 trades en ventana BULL ({BULL_TIMERANGE}). "
    "Regenerar fixtures: python tests/fixtures/generate_data.py"
  )


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env (copiar desde .env.example)")
def test_mean_rev_executes_trades_in_range(fixtures_datadir: Path) -> None:
  """MeanRevBB en ventana RANGE — ciclo mean-rev end-to-end."""
  result = _run_backtest("MeanRevBB", RANGE_TIMERANGE)
  output = (result.stdout or "") + (result.stderr or "")
  assert result.returncode == 0, f"Backtest RANGE falló\n{output[-3000:]}"
  trades = _parse_trade_count(output, "MeanRevBB")
  assert trades is not None, f"No se pudo parsear trades\n{output[-2000:]}"
  assert trades > 0, (
    f"MeanRevBB ejecutó 0 trades en ventana RANGE ({RANGE_TIMERANGE}). "
    "Regenerar fixtures: python tests/fixtures/generate_data.py"
  )


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env")
def test_regime_switcher_executes_both_branches(fixtures_datadir: Path) -> None:
  """RegimeSwitcher en fixtures — trades con ambas ramas BULL+RANGE."""
  result = _run_backtest("RegimeSwitcher", DEFAULT_TIMERANGE)
  output = (result.stdout or "") + (result.stderr or "")
  assert result.returncode == 0, f"Backtest RegimeSwitcher falló\n{output[-3000:]}"
  trades = _parse_trade_count(output, "RegimeSwitcher")
  assert trades is not None, f"No se pudo parsear trades\n{output[-2000:]}"
  assert trades > 0, "RegimeSwitcher ejecutó 0 trades en fixtures"


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env")
def test_regime_switcher_exit_respects_enter_tag(fixtures_datadir: Path) -> None:
  """
  Sin cruces de señal entre ramas; dispatch ejercitado con stop ensanchado.
  """
  cmd = [
    "docker",
    "compose",
    "run",
    "--rm",
    "--entrypoint",
    "python",
    "freqtrade",
    "user_data/tools/trade_tag_exit_check.py",
    "--strategy",
    "RegimeSwitcherWideStop",
    "--timerange",
    DEFAULT_TIMERANGE,
    "--min-signal-exits",
    "1",
    *_tool_config_flags(),
  ]
  result = subprocess.run(
    cmd,
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=600,
    check=False,
  )
  output = (result.stdout or "") + (result.stderr or "")
  assert result.returncode == 0, f"trade_tag_exit_check falló\n{output[-4000:]}"
  assert "OK: salidas respetan enter_tag" in output
  assert "cierres por señal custom_exit:" in output
  # Dispatch ejercitado — no paso vacío por 0 señales
  import re

  m = re.search(r"cierres por señal custom_exit:\s*(\d+)", output)
  assert m and int(m.group(1)) >= 1, f"Dispatch no ejercitado\n{output[-2000:]}"


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env")
def test_grid_dca_executes_trades(fixtures_datadir: Path) -> None:
  """GridDCA en fixtures — al menos un trade en ventana DCA."""
  result = _run_backtest("GridDCA", DCA_TIMERANGE)
  output = (result.stdout or "") + (result.stderr or "")
  assert result.returncode == 0, f"Backtest GridDCA falló\n{output[-3000:]}"
  trades = _parse_trade_count(output, "GridDCA")
  assert trades is not None, f"No se pudo parsear trades\n{output[-2000:]}"
  assert trades > 0, "GridDCA ejecutó 0 trades en ventana DCA"


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="Docker no disponible")
@pytest.mark.skipif(not _env_file_exists(), reason="Falta archivo .env")
def test_grid_dca_cycle_and_budget(fixtures_datadir: Path) -> None:
  """Ciclo DCA→stop ejercitado; presupuesto respetado."""
  cmd = [
    "docker",
    "compose",
    "run",
    "--rm",
    "--entrypoint",
    "python",
    "freqtrade",
    "user_data/tools/grid_dca_check.py",
    "--strategy",
    "GridDCAFixture",
    "--timerange",
    DCA_TIMERANGE,
    "--min-position-adjustments",
    "3",
    "--require-stop-after-dca",
    "--pairs",
    "BTC/USDT",
    *_config_flags(fixtures=False),
  ]
  result = subprocess.run(
    cmd,
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=600,
    check=False,
  )
  output = (result.stdout or "") + (result.stderr or "")
  assert result.returncode == 0, f"grid_dca_check falló\n{output[-4000:]}"
  assert "OK: auditoría GridDCA completada" in output


def test_no_hardcoded_secrets_in_repo() -> None:
  """Escaneo básico: no debe haber patrones de API key en código versionado."""
  patterns = ["sk-live-", "AKIA", "api_secret = \"", "secret = \"abc"]
  offenders: list[str] = []
  for path in ROOT.rglob("*"):
    if not path.is_file():
      continue
    if path.suffix in {".pyc", ".feather"} or "node_modules" in path.parts:
      continue
    if path.name in {".env", ".env.example"}:
      continue
    if path.name == "test_smoke_backtest.py":
      continue
    if ".git" in path.parts:
      continue
    try:
      text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
      continue
    for pattern in patterns:
      if pattern in text:
        offenders.append(f"{path}: {pattern}")
  assert not offenders, "Posibles secretos hardcodeados:\n" + "\n".join(offenders)


def test_base_config_is_dry_run() -> None:
  config = json.loads((ROOT / "user_data" / "config" / "base.json").read_text())
  assert config["dry_run"] is True


def test_configs_use_env_placeholders_for_secrets() -> None:
  base = (ROOT / "user_data" / "config" / "base.json").read_text()
  assert "${FREQTRADE__EXCHANGE__KEY}" in base
  assert "${FREQTRADE__TELEGRAM__TOKEN}" in base
  assert "${FREQTRADE__API_SERVER__PASSWORD}" in base
