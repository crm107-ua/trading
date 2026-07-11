"""Plan en seco de validación — sin lock ni ejecución Docker."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from pipeline.config_hash import config_metadata, resolve_config_paths
from pipeline.freqtrade_cli import format_freqtrade_command
from pipeline.git_provenance import current_git_hash
from pipeline.strategy_spaces import hyperopt_spaces_for
from pipeline.strategy_warmup import earliest_train_start, startup_candles_for_strategy, warmup_days
from pipeline.timerange_split import compute_is_oos_split, resolve_data_end
from pipeline.walk_forward import generate_walk_forward_windows

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "user_data" / "data" / "binance"
PROFILE_DEFAULTS = {
  "smoke": {"epochs": 30, "seeds": 1, "walk_forward": False, "min_trades": 30},
  "full": {"epochs": 300, "seeds": 3, "walk_forward": True, "min_trades": 100},
}
SEEDS = [42, 123, 456]


@dataclass
class PlannedCommand:
  phase: str
  label: str
  command: str


def build_validation_plan(
  *,
  strategy: str,
  timerange: str,
  profile: str,
  epochs: int | None = None,
  seeds: int | None = None,
  wf_epochs: int | None = None,
  enable_protections: bool = True,
  skip_walk_forward: bool = False,
  extra_config_paths: list[Path] | None = None,
) -> dict:
  defaults = PROFILE_DEFAULTS[profile]
  epochs_n = epochs if epochs is not None else defaults["epochs"]
  wf_epochs_n = wf_epochs if wf_epochs is not None else epochs_n
  seeds_n = seeds if seeds is not None else defaults["seeds"]
  min_trades_n = int(defaults["min_trades"])
  do_wf = defaults["walk_forward"] and not skip_walk_forward
  opt_spaces = hyperopt_spaces_for(strategy)
  config_paths = resolve_config_paths(extra_config_paths)
  candles, tf = startup_candles_for_strategy(strategy)

  data_end = resolve_data_end(DATA_DIR)
  split = compute_is_oos_split(timerange, data_end=data_end)
  wf_train_min = earliest_train_start(split.full_start, strategy)
  windows = (
    generate_walk_forward_windows(
      split.full_start,
      split.full_end,
      earliest_train_start=wf_train_min,
    )
    if do_wf
    else []
  )

  commands: list[PlannedCommand] = []
  params_archive = f"user_data/validation_reports/{strategy}/<run_id>/params/"

  commands.append(
    PlannedCommand(
      "precheck",
      "clear_params",
      f"# rm user_data/strategies/{strategy}.json (clear_strategy_params)",
    )
  )
  commands.append(
    PlannedCommand(
      "baseline_oos",
      "defaults",
      format_freqtrade_command(
        "backtesting",
        strategy,
        split.oos_timerange,
        config_paths=config_paths,
        enable_protections=enable_protections,
      ),
    )
  )

  for seed in SEEDS[:seeds_n]:
    label = f"is_seed{seed}"
    commands.append(
      PlannedCommand(
        "hyperopt_is",
        label,
        format_freqtrade_command(
          "hyperopt",
          strategy,
          split.is_timerange,
          config_paths=config_paths,
          epochs=epochs_n,
          random_state=seed,
          spaces=opt_spaces,
          min_trades=min_trades_n,
          enable_protections=enable_protections,
        ),
      )
    )
    for phase, tr in (("backtest_is", split.is_timerange), ("backtest_oos", split.oos_timerange)):
      commands.append(
        PlannedCommand(
          phase,
          f"{label}",
          format_freqtrade_command(
            "backtesting",
            strategy,
            tr,
            config_paths=config_paths,
            enable_protections=enable_protections,
          )
          + f"  # install {params_archive}{label}.json",
        )
      )

  for window in windows:
    wf_label = f"wf{window.index}_train"
    commands.append(
      PlannedCommand(
        "wf_hyperopt",
        wf_label,
        format_freqtrade_command(
          "hyperopt",
          strategy,
          window.train_timerange,
          config_paths=config_paths,
          epochs=wf_epochs_n,
          random_state=42,
          spaces=opt_spaces,
          min_trades=min_trades_n,
          enable_protections=enable_protections,
        ),
      )
    )
    commands.append(
      PlannedCommand(
        "wf_backtest_train",
        wf_label,
        format_freqtrade_command(
          "backtesting",
          strategy,
          window.train_timerange,
          config_paths=config_paths,
          enable_protections=enable_protections,
        ),
      )
    )
    commands.append(
      PlannedCommand(
        "wf_backtest_test",
        f"wf{window.index}_test",
        format_freqtrade_command(
          "backtesting",
          strategy,
          window.test_timerange,
          config_paths=config_paths,
          enable_protections=enable_protections,
        ),
      )
    )

  return {
    "dry_plan": True,
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "strategy": strategy,
    "profile": profile,
    "git_hash": current_git_hash(),
    **config_metadata(config_paths),
    "timerange_requested": timerange,
    "split": split.to_dict(),
    "epochs": epochs_n,
    "wf_epochs": wf_epochs_n,
    "seeds": seeds_n,
    "min_trades": min_trades_n,
    "hyperopt_spaces": opt_spaces,
    "enable_protections": enable_protections,
    "walk_forward_enabled": do_wf,
    "warmup": {
      "startup_candles": candles,
      "timeframe": tf,
      "warmup_days": warmup_days(strategy),
      "earliest_train_start": wf_train_min.isoformat(),
      "data_start": split.full_start.isoformat(),
    },
    "walk_forward_windows": [w.to_dict() for w in windows],
    "params_archive_dir": params_archive,
    "files_to_clear_before_run": [f"user_data/strategies/{strategy}.json"],
    "commands": [asdict(c) for c in commands],
  }


def format_plan_text(plan: dict) -> str:
  lines = [
    f"DRY-PLAN {plan['strategy']} profile={plan['profile']}",
    f"git={plan['git_hash']}",
    f"IS:  {plan['split']['is_timerange']}",
    f"OOS: {plan['split']['oos_timerange']}",
    f"epochs={plan['epochs']} wf_epochs={plan['wf_epochs']} seeds={plan['seeds']}",
    f"config_files={plan['config_files']}",
    f"config_merged_sha256={plan['config_merged_sha256']}",
    (
      f"warmup: {plan['warmup']['startup_candles']}x{plan['warmup']['timeframe']} "
      f"= {plan['warmup']['warmup_days']}d train_desde {plan['warmup']['earliest_train_start']}"
    ),
    f"walk_forward: {len(plan.get('walk_forward_windows') or [])} ventanas",
    "",
    "Comandos:",
  ]
  for cmd in plan["commands"]:
    lines.append(f"  [{cmd['phase']}] {cmd['label']}:")
    lines.append(f"    {cmd['command']}")
  return "\n".join(lines)
