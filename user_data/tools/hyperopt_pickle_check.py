"""
Inspección de serialización hyperopt (orientativa — no predice si -j 2 funciona).

Uso:
  # Laboratorio (config completo user_data):
  docker compose run --rm --entrypoint python freqtrade user_data/tools/hyperopt_pickle_check.py MeanRevBB

  # Control vainilla (SampleStrategy + config mínimo, sin user_data/strategies):
  docker compose run --rm --entrypoint python freqtrade user_data/tools/hyperopt_pickle_check.py --vanilla

  # Durante run_validation activo: aborta salvo --force
  # Puede eliminar hyperopt_tickerdata.pkl (contingente por versión/modo — ver docs/VALIDATION.md)

Test decisivo de paralelismo: scripts/probe_vanilla_hyperopt_parallel.ps1
Documentación: docs/HYPEROPT_PARALLEL_BISECT.md
"""

from __future__ import annotations

import argparse
import pickletools
import sys
import traceback
import types
from io import BytesIO

from joblib.externals import cloudpickle

from freqtrade.configuration import Configuration
from freqtrade.optimize.hyperopt import Hyperopt
from freqtrade.resolvers import StrategyResolver

DEFAULT_RECURSION = sys.getrecursionlimit()
HIGH_RECURSION = max(10_000, DEFAULT_RECURSION * 4)


def _pickle_label(obj: object, label: str) -> bool:
  ok_default, err_default = _try_pickle(obj, DEFAULT_RECURSION)
  if ok_default:
    print(f"OK: {label} (recursion={DEFAULT_RECURSION})")
    return True

  print(f"FAIL: {label} (recursion={DEFAULT_RECURSION}) — {err_default}")
  ok_high, err_high = _try_pickle(obj, HIGH_RECURSION)
  if ok_high:
    print(
      f"HINT: {label} serializa con recursion={HIGH_RECURSION} — "
      "profundidad legítima (objeto-cebolla), no referencia circular pura."
    )
    return False

  print(f"FAIL: {label} (recursion={HIGH_RECURSION}) — {err_high}")
  print(f"HINT: {label} — probable referencia circular o no serializable con cualquier límite.")
  return False


def _try_pickle(obj: object, recursion_limit: int) -> tuple[bool, str]:
  old = sys.getrecursionlimit()
  try:
    sys.setrecursionlimit(recursion_limit)
    cloudpickle.dumps(obj)
    return True, ""
  except Exception as exc:
    return False, f"{type(exc).__name__}: {exc}"
  finally:
    sys.setrecursionlimit(old)


def _inspect_closure(func: object) -> None:
  print("==> Inspección closure")
  if not isinstance(func, types.FunctionType):
    print(f"    no es función, es {type(func).__name__}")
    return
  closure = func.__closure__
  if not closure:
    print("    sin __closure__")
    return
  for idx, cell in enumerate(closure):
    try:
      val = cell.cell_contents
      print(f"    cell[{idx}]: {type(val).__name__} — {repr(val)[:120]}")
    except ValueError as exc:
      print(f"    cell[{idx}]: <empty> — {exc}")


def _pickletools_disasm(obj: object) -> None:
  print("==> pickletools.dis (primeros opcodes)")
  try:
    payload = cloudpickle.dumps(obj)
    pickletools.dis(BytesIO(payload))
  except Exception as exc:
    print(f"    pickletools no disponible: {type(exc).__name__}: {exc}")


def _check_run_lock(force: bool) -> None:
  try:
    if "/freqtrade" not in sys.path:
      sys.path.insert(0, "/freqtrade")
    from pipeline.run_lock import require_no_active_validation  # noqa: E402

    lock = require_no_active_validation(force=force, tool="hyperopt_pickle_check")
    if lock is not None:
      print(
        f"WARN: --force — validación activa ({lock.strategy} pid={lock.pid} "
        f"started_at={lock.started_at})"
      )
  except Exception as exc:
    if not force:
      print(f"ABORT: {exc}")
      raise SystemExit(2) from exc


def _build_config(*, vanilla: bool, strategy_name: str) -> dict:
  if vanilla:
    config = Configuration.from_files(["user_data/fixtures/vanilla_hyperopt.json"])
    config.update(
      {
        "strategy": "SampleStrategy",
        "strategy_path": "freqtrade/templates",
        "timerange": "20240101-20240201",
        "timeframe": "1h",
        "hyperopt_loss": "SharpeHyperOptLoss",
        "spaces": ["buy", "sell", "roi", "stoploss"],
        "runmode": "hyperopt",
      }
    )
    return config

  config = Configuration.from_files(
    ["user_data/config/base.json", "user_data/config/backtest.json"]
  )
  config.update(
    {
      "strategy": strategy_name,
      "strategy_path": "user_data/strategies",
      "hyperopt_path": "user_data/hyperopts",
      "timerange": "20240101-20240201",
      "hyperopt_loss": "QuantRobustLoss",
      "spaces": ["buy", "sell"],
      "runmode": "hyperopt",
    }
  )
  return config


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Diagnóstico pickle hyperopt Freqtrade")
  parser.add_argument("strategy", nargs="?", default="MeanRevBB")
  parser.add_argument(
    "--vanilla",
    action="store_true",
    help="SampleStrategy de freqtrade/templates + config mínimo (control)",
  )
  parser.add_argument(
    "--force",
    action="store_true",
    help="Ejecutar aunque haya run_validation activo (peligroso con volumen compartido)",
  )
  parser.add_argument(
    "--inspect",
    action="store_true",
    help="Inspeccionar __closure__ y pickletools del wrapper",
  )
  args = parser.parse_args(argv)

  _check_run_lock(args.force)

  strategy_name = "SampleStrategy" if args.vanilla else args.strategy
  mode = "vanilla" if args.vanilla else "lab"
  print(f"==> hyperopt_pickle_check mode={mode} strategy={strategy_name}")

  config = _build_config(vanilla=args.vanilla, strategy_name=strategy_name)

  strategy = StrategyResolver.load_strategy(config)
  ok_strategy = _pickle_label(strategy, f"estrategia {strategy_name}")

  if args.vanilla:
    ok_loss = True
    print("SKIP: QuantRobustLoss (modo vanilla usa SharpeHyperOptLoss builtin)")
  else:
    sys.path.insert(0, "user_data/hyperopts")
    from QuantRobustLoss import QuantRobustLoss  # noqa: E402

    ok_loss = _pickle_label(QuantRobustLoss, "QuantRobustLoss")

  ho = Hyperopt(config)
  params = {"buy": {}, "sell": {}, "roi": {}, "stoploss": {}}
  wrapped = ho.hyperopter.generate_optimizer_wrapped(params)
  if args.inspect:
    _inspect_closure(wrapped)
    _pickletools_disasm(wrapped)

  ok_wrapped = _pickle_label(wrapped, "generate_optimizer_wrapped (freqtrade)")

  if ok_wrapped:
    print("RESULT: hyperopt paralelo (-j > 1) debería funcionar con esta configuración.")
    return 0

  print(
    "RESULT: generate_optimizer_wrapped NO serializa. "
    f"mode={mode} strategy_ok={ok_strategy} loss_ok={ok_loss}. "
    "Si --vanilla también falla → entorno Docker/joblib; si solo lab → config/user_data."
  )
  return 1


if __name__ == "__main__":
  raise SystemExit(main())
