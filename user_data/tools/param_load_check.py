#!/usr/bin/env python3
"""Verifica carga de parámetros en backtest (fallo-en-vacío #5)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategies"))
sys.path.insert(0, "/freqtrade/pipeline")

from freqtrade.enums import RunMode
from freqtrade.exchange import Exchange
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.resolvers import StrategyResolver

from params_manager import (  # type: ignore[import-not-found]
  clear_strategy_params,
  install_strategy_params,
  verify_params_loaded,
)


def _parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Auditoría carga de parámetros")
  parser.add_argument("--strategy", required=True)
  parser.add_argument("--params", required=True)
  parser.add_argument("--timerange", required=True)
  return parser.parse_args()


def main() -> int:
  args = _parse_args()
  from freqtrade.configuration import Configuration

  params_path = Path(args.params)
  if not params_path.is_absolute():
    params_path = Path("/freqtrade") / params_path

  clear_strategy_params(args.strategy)
  install_strategy_params(args.strategy, params_path)

  root = Path("/freqtrade")
  config = Configuration.from_files(
    [
      str(root / "user_data/config/base.json"),
      str(root / "user_data/config/backtest.json"),
    ]
  )
  if hasattr(config, "get_config"):
    config = config.get_config()
  config["runmode"] = RunMode.BACKTEST
  config["strategy"] = args.strategy
  config["strategy_path"] = str(root / "user_data/strategies")
  config["timerange"] = args.timerange

  import io
  from contextlib import redirect_stderr, redirect_stdout

  log_buffer = io.StringIO()
  with redirect_stdout(log_buffer), redirect_stderr(log_buffer):
    exchange = Exchange(config)
    strategy = StrategyResolver.load_strategy(config)
    strategy.ft_load_hyper_params(False)
    bt = Backtesting(config, exchange)
    bt._set_strategy(strategy)
    data, tr = bt.load_bt_data()
    processed = bt.strategy.advise_all_indicators(data)
    bt.backtest(processed=processed, start_date=tr.startdt, end_date=tr.stopdt)

  log_output = log_buffer.getvalue()
  ok, issues = verify_params_loaded(params_path, log_output, allow_defaults=False)
  if not ok:
    print("FAIL: params no coinciden:")
    for issue in issues:
      print(f"  {issue}")
    return 1

  print("OK: parámetros cargados coinciden con archivo archivado")
  return 0


if __name__ == "__main__":
  sys.exit(main())
