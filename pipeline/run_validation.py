"""
Orquestador Fase 4 — IS/OOS, semillas, walk-forward y veredicto.

Perfiles:
  smoke  — 30 epochs, 1 semilla, sin walk-forward (CI / fontanería)
  full   — 300 epochs, 3 semillas, walk-forward 12m/3m

  python -m pipeline.run_validation GridDCA --profile smoke
  python -m pipeline.run_validation validate MeanRevBB --profile full
"""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterator

import typer
from rich.console import Console
from rich.table import Table

from pipeline.config_hash import config_metadata
from pipeline.freqtrade_cli import (
  docker_runtime_info,
  hyperopt_job_workers,
  parse_backtest_metrics,
  run_backtest,
  run_hyperopt,
  stop_ephemeral_freqtrade_containers,
)
from pipeline.hyperopt_checkpoint import archive_hyperopt_results
from pipeline.hyperopt_resume import adopt_partial_enabled, try_adopt_partial_hyperopt
from pipeline.params_manager import (
  archive_strategy_params,
  clear_strategy_params,
  install_strategy_params,
  param_divergence,
  params_file_exists,
  read_strategy_params,
  verify_params_loaded,
)
from pipeline.timerange_split import compute_is_oos_split, resolve_data_end
from pipeline.verdict import Verdict
from pipeline.verdict_engine import SeedRunResult, VerdictInput, compute_verdict
from pipeline.regime_stats import regime_distribution_for_timerange
from pipeline.git_provenance import current_git_hash, record_step_git
from pipeline.run_lock import (
  ValidationRunActiveError,
  acquire_lock,
  release_lock,
  touch_lock_heartbeat,
)
from pipeline.strategy_spaces import hyperopt_spaces_for
from pipeline.strategy_warmup import earliest_train_start, warmup_days
from pipeline.walk_forward import (
  OosSegmentResult,
  WalkForwardWindow,
  generate_walk_forward_windows,
  stitch_oos_equity,
  walk_forward_efficiency,
)
from pipeline.wf_resume import (
  WfWindowRecord,
  adopt_or_recover_wf_window,
  evaluate_wf_adoption,
  merge_checkpoint_wf_completed,
  save_wf_segment,
)

console = Console()
ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "user_data" / "validation_reports"
DATA_DIR = ROOT / "user_data" / "data" / "binance"
CHECKPOINT_NAME = "checkpoint.json"


class Profile(str, Enum):
  smoke = "smoke"
  full = "full"


PROFILE_DEFAULTS = {
  Profile.smoke: {"epochs": 30, "seeds": 1, "walk_forward": False, "min_trades": 30},
  Profile.full: {"epochs": 300, "seeds": 3, "walk_forward": True, "min_trades": 100},
}


def _seed_values(count: int) -> list[int]:
  return [42, 123, 456][:count]


def _run_dir(strategy: str, run_id: str) -> Path:
  path = REPORTS_DIR / strategy / run_id
  path.mkdir(parents=True, exist_ok=True)
  return path


def _checkpoint_path(run_path: Path) -> Path:
  return run_path / CHECKPOINT_NAME


def _save_checkpoint(run_path: Path, payload: dict) -> None:
  _checkpoint_path(run_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_checkpoint(run_path: Path) -> dict | None:
  path = _checkpoint_path(run_path)
  if not path.is_file():
    return None
  return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def _validation_lock(*, strategy: str, run_id: str, profile: str) -> Iterator[None]:
  acquire_lock(strategy=strategy, run_id=run_id, profile=profile)
  try:
    yield
  finally:
    release_lock()


def _seed_result_from_dict(data: dict) -> SeedRunResult:
  return SeedRunResult(
    seed=int(data["seed"]),
    is_metrics=dict(data["is_metrics"]),
    oos_metrics=dict(data["oos_metrics"]),
    params_file=str(data["params_file"]),
    param_divergence_vs_seed0=float(data.get("param_divergence_vs_seed0") or 0.0),
  )


def _hyperopt_and_archive(
  strategy: str,
  timerange: str,
  *,
  epochs: int,
  seed: int,
  enable_protections: bool,
  archive_dir: Path,
  label: str,
  min_trades: int,
  spaces: list[str],
  adopt_partial: bool = False,
  context: str | None = None,
  archive_extra_meta: dict | None = None,
) -> tuple[Path | None, str]:
  """Hyperopt IS con params limpios; archiva el json generado."""
  ctx = context or f"seed={seed}"
  clear_strategy_params(strategy)
  if params_file_exists(strategy):
    raise RuntimeError(f"FAIL: {strategy}.json no se limpió antes de hyperopt ({ctx})")

  if adopt_partial_enabled(adopt_partial):
    adoption = try_adopt_partial_hyperopt(strategy, epochs=epochs, seed=seed)
    if adoption is not None:
      console.print(
        f"[yellow]==> Hyperopt adoptado desde {adoption.source_file} "
        f"({adoption.epochs_done}/{adoption.epochs_requested}, "
        f"ratio={adoption.completion_ratio:.1%})[/yellow]"
      )
      archived = archive_strategy_params(strategy, archive_dir, label, extra_meta=archive_extra_meta)
      if archived is None:
        raise RuntimeError(f"adopción no exportó {strategy}.json ({ctx})")
      return archived, adoption.note

  result = run_hyperopt(
    strategy,
    timerange,
    epochs=epochs,
    random_state=seed,
    enable_protections=enable_protections,
    min_trades=min_trades,
    spaces=spaces,
  )
  if result.returncode != 0:
    from pipeline.freqtrade_cli import _extract_error_tail

    raise RuntimeError(f"hyperopt falló ({ctx})\n{_extract_error_tail(result.output)}")

  archived = archive_strategy_params(
    strategy, archive_dir, label, extra_meta=archive_extra_meta
  )
  if archived is None:
    raise RuntimeError(f"hyperopt no exportó {strategy}.json ({ctx})")

  return archived, result.output


def _archive_seed_hyperopt(run_path: Path, seed: int) -> list[str]:
  dest = run_path / "hyperopt_checkpoints" / f"is_seed{seed}"
  return archive_hyperopt_results(dest)


def _backtest_with_params(
  strategy: str,
  timerange: str,
  params_file: Path,
  *,
  enable_protections: bool,
  allow_defaults: bool,
) -> tuple[dict, str, Path]:
  clear_strategy_params(strategy)
  install_strategy_params(strategy, params_file)

  result, zip_path = run_backtest(strategy, timerange, enable_protections=enable_protections)
  ok, issues = verify_params_loaded(params_file, result.output, allow_defaults=allow_defaults)
  if not ok:
    raise RuntimeError(
      "param load check falló:\n  " + "\n  ".join(issues) + f"\n{result.output[-2000:]}"
    )
  if result.returncode != 0:
    raise RuntimeError(f"backtest falló\n{result.output[-3000:]}")
  if zip_path is None:
    raise RuntimeError("sin zip de backtest tras ejecución")
  metrics = parse_backtest_metrics(zip_path, strategy)
  return metrics, result.output, zip_path


def _baseline_oos_backtest(
  strategy: str,
  oos_timerange: str,
  *,
  enable_protections: bool,
) -> tuple[dict, Path]:
  """OOS con defaults — sin json de params."""
  removed = clear_strategy_params(strategy)
  if params_file_exists(strategy):
    raise RuntimeError("FAIL: no se pudo limpiar params antes de baseline OOS")
  _ = removed

  result, zip_path = run_backtest(strategy, oos_timerange, enable_protections=enable_protections)
  if params_file_exists(strategy):
    raise RuntimeError("baseline OOS contaminado: apareció json de params inesperado")

  if result.returncode != 0:
    raise RuntimeError(f"baseline OOS falló\n{result.output[-2000:]}")
  if zip_path is None:
    raise RuntimeError("sin zip baseline OOS")
  return parse_backtest_metrics(zip_path, strategy), zip_path


def main(
  strategy: str = typer.Argument(..., help="Estrategia Freqtrade"),
  timerange: str = typer.Option("20210101-", help="Ventana completa"),
  profile: Profile = typer.Option(Profile.smoke, help="smoke o full"),
  epochs: int | None = typer.Option(None, help="Override epochs"),
  seeds: int | None = typer.Option(None, help="Override semillas"),
  enable_protections: bool = typer.Option(True, help="Protecciones en todos los pasos"),
  skip_walk_forward: bool = typer.Option(False, help="Omitir walk-forward"),
  skip_hyperopt: bool = typer.Option(False, help="Solo split + baseline"),
  resume_run_id: str | None = typer.Option(
    None, help="Reanudar run interrumpido (mismo run_id, salta semillas completadas)"
  ),
  adopt_partial_hyperopt: bool = typer.Option(
    False,
    help="Adoptar .fthypt parcial ≥95%% en lugar de re-hyperopt (reanudación barata)",
  ),
  wf_epochs: int | None = typer.Option(
    None,
    "--wf-epochs",
    help="Epochs hyperopt por ventana walk-forward (default: igual que --epochs del perfil)",
  ),
) -> None:
  """Validación Fase 4 — IS/OOS, semillas, walk-forward, veredicto."""
  try:
    _run_validation(
      strategy=strategy,
      timerange=timerange,
      profile=profile,
      epochs=epochs,
      seeds=seeds,
      enable_protections=enable_protections,
      skip_walk_forward=skip_walk_forward,
      skip_hyperopt=skip_hyperopt,
      resume_run_id=resume_run_id,
      adopt_partial_hyperopt=adopt_partial_hyperopt,
      wf_epochs=wf_epochs,
    )
  except ValidationRunActiveError as exc:
    console.print(f"[red]{exc}[/red]")
    raise typer.Exit(code=3) from exc
  finally:
    stopped = stop_ephemeral_freqtrade_containers()
    if stopped:
      console.print(
        f"[dim]contenedores efímeros detenidos al salir: {len(stopped)}[/dim]"
      )


def _run_validation(
  *,
  strategy: str,
  timerange: str,
  profile: Profile,
  epochs: int | None,
  seeds: int | None,
  enable_protections: bool,
  skip_walk_forward: bool,
  skip_hyperopt: bool,
  resume_run_id: str | None,
  adopt_partial_hyperopt: bool,
  wf_epochs: int | None,
) -> None:
  defaults = PROFILE_DEFAULTS[profile]
  epochs_n = epochs if epochs is not None else defaults["epochs"]
  wf_epochs_n = wf_epochs if wf_epochs is not None else epochs_n
  seeds_n = seeds if seeds is not None else defaults["seeds"]
  min_trades_n = int(defaults["min_trades"])
  opt_spaces = hyperopt_spaces_for(strategy)
  do_wf = defaults["walk_forward"] and not skip_walk_forward

  checkpoint: dict | None = None
  if resume_run_id:
    run_id = resume_run_id
    run_path = _run_dir(strategy, run_id)
    checkpoint = _load_checkpoint(run_path)
    if checkpoint is None:
      raise RuntimeError(f"sin checkpoint.json en {run_path}")
    console.print(f"[yellow]==> Reanudando run_id={run_id}[/yellow]")
  else:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_path = _run_dir(strategy, run_id)

  params_archive = run_path / "params"
  params_archive.mkdir(exist_ok=True)

  if not (DATA_DIR / "BTC_USDT-1h.feather").exists():
    console.print("[red]Falta user_data/data — ejecutar scripts/download_data.ps1[/red]")
    raise typer.Exit(code=1)

  data_end = resolve_data_end(DATA_DIR)
  split = compute_is_oos_split(timerange, data_end=data_end)

  with _validation_lock(strategy=strategy, run_id=run_id, profile=profile.value):
    report: dict = {
      "strategy": strategy,
      "profile": profile.value,
      "conclusive": profile == Profile.full,
      "conclusive_note": (
        "Veredicto vinculante — perfil full con semillas y walk-forward completos."
        if profile == Profile.full
        else "NO CONCLUYENTE — perfil smoke (epochs/seeds reducidos). No citar veredicto como validación."
      ),
      "run_id": run_id,
      "git_hash": current_git_hash(),
      **config_metadata(),
      "timerange_requested": timerange,
      "split": split.to_dict(),
      "oos_regime_distribution": regime_distribution_for_timerange(split.oos_timerange),
      "epochs": epochs_n,
      "wf_epochs": wf_epochs_n,
      "seeds": seeds_n,
      "min_trades": min_trades_n,
      "hyperopt_spaces": opt_spaces,
      "hyperopt_job_workers": hyperopt_job_workers(),
      "hyperopt_reproducibility_note": (
        "La secuencia hyperopt depende de --random-state y -j. "
        "Cambiar -j invalida comparación con runs previos; re-lanzar la estrategia completa."
      ),
      "docker_runtime": docker_runtime_info(),
      "enable_protections": enable_protections,
      "walk_forward_enabled": do_wf,
      "adopt_partial_hyperopt": adopt_partial_enabled(adopt_partial_hyperopt),
      "steps": {},
      "verdict": Verdict.DUDOSA.value,
      "reasons": [],
    }

    record_step_git(report, "validation_start")
    touch_lock_heartbeat()

    console.print(f"[bold]==> Validación {strategy}[/bold] profile={profile.value}")
    console.print(f"    IS:  {split.is_timerange}")
    console.print(f"    OOS: {split.oos_timerange}")

    completed_seeds: set[int] = set()
    seed_results: list[SeedRunResult] = []
    seed_params_raw: list[dict] = []
    baseline_oos: dict

    if checkpoint:
      completed_seeds = {int(s) for s in checkpoint.get("completed_seeds", [])}
      seed_results = [_seed_result_from_dict(s) for s in checkpoint.get("seed_results", [])]
      seed_params_raw = list(checkpoint.get("seed_params_raw", []))
      if checkpoint.get("baseline_oos"):
        baseline_oos = dict(checkpoint["baseline_oos"])
        report["steps"]["baseline_oos_defaults"] = baseline_oos
        console.print("[dim]Baseline OOS — restaurado desde checkpoint[/dim]")
    else:
      baseline_oos = {}

    if not checkpoint or not checkpoint.get("baseline_oos"):
      console.print("[cyan]==> Baseline OOS (defaults, params limpios)[/cyan]")
      try:
        baseline_oos, baseline_zip = _baseline_oos_backtest(
          strategy,
          split.oos_timerange,
          enable_protections=enable_protections,
        )
        report["steps"]["baseline_oos_defaults"] = baseline_oos
        shutil.copy2(baseline_zip, run_path / "baseline_oos.zip")
      finally:
        clear_strategy_params(strategy)
      _save_checkpoint(
        run_path,
        {
          "run_id": run_id,
          "strategy": strategy,
          "baseline_oos": baseline_oos,
          "completed_seeds": sorted(completed_seeds),
          "seed_results": [asdict(s) for s in seed_results],
          "seed_params_raw": seed_params_raw,
        },
      )

    if skip_hyperopt:
      record_step_git(report, "verdict")
      report["notes"] = ["skip_hyperopt=True"]
      _write_report(run_path, report)
      return

    record_step_git(report, "seeds")
    touch_lock_heartbeat()

    for seed in _seed_values(seeds_n):
      if seed in completed_seeds:
        console.print(f"[dim]==> Semilla {seed} — ya en checkpoint, omitiendo[/dim]")
        continue

      label = f"is_seed{seed}"
      console.print(f"[cyan]==> Hyperopt IS seed={seed} ({epochs_n} epochs)[/cyan]")
      archived, _ = _hyperopt_and_archive(
        strategy,
        split.is_timerange,
        epochs=epochs_n,
        seed=seed,
        enable_protections=enable_protections,
        archive_dir=params_archive,
        label=label,
        min_trades=min_trades_n,
        spaces=opt_spaces,
        adopt_partial=adopt_partial_hyperopt,
      )
      hyperopt_files = _archive_seed_hyperopt(run_path, seed)

      console.print(f"[cyan]==> Backtest IS seed={seed} (params archivados)[/cyan]")
      is_metrics, _, is_zip = _backtest_with_params(
        strategy,
        split.is_timerange,
        archived,
        enable_protections=enable_protections,
        allow_defaults=False,
      )
      shutil.copy2(is_zip, run_path / f"is_seed{seed}.zip")

      console.print(f"[cyan]==> Backtest OOS seed={seed}[/cyan]")
      oos_metrics, _, oos_zip = _backtest_with_params(
        strategy,
        split.oos_timerange,
        archived,
        enable_protections=enable_protections,
        allow_defaults=False,
      )
      shutil.copy2(oos_zip, run_path / f"oos_seed{seed}.zip")

      raw = read_strategy_params(strategy) or json.loads(archived.read_text(encoding="utf-8"))
      seed_params_raw.append(raw)
      clear_strategy_params(strategy)

      seed_results.append(
        SeedRunResult(
          seed=seed,
          is_metrics=is_metrics,
          oos_metrics=oos_metrics,
          params_file=str(archived),
        )
      )
      completed_seeds.add(seed)
      touch_lock_heartbeat()
      _save_checkpoint(
        run_path,
        {
          "run_id": run_id,
          "strategy": strategy,
          "baseline_oos": baseline_oos,
          "completed_seeds": sorted(completed_seeds),
          "seed_results": [asdict(s) for s in seed_results],
          "seed_params_raw": seed_params_raw,
          "hyperopt_checkpoints": {str(seed): hyperopt_files},
        },
      )

    # Divergencia entre semillas
    max_div = 0.0
    if len(seed_params_raw) > 1:
      for i in range(1, len(seed_params_raw)):
        div = param_divergence(seed_params_raw[0], seed_params_raw[i])
        seed_results[i].param_divergence_vs_seed0 = div
        max_div = max(max_div, div)
    report["steps"]["seeds"] = [asdict(s) for s in seed_results]
    report["max_param_divergence"] = max_div

    # Walk-forward
    wfe_value: float | None = None
    is_profits_wf: list[float] = []
    oos_profits_wf: list[float] = []

    if do_wf:
      record_step_git(report, "walk_forward")
      touch_lock_heartbeat()
      wf_warmup_days = warmup_days(strategy)
      wf_train_min = earliest_train_start(split.full_start, strategy)
      console.print(
        f"[cyan]==> Walk-forward 12m/3m ({wf_epochs_n} epochs/ventana, "
        f"warmup>={wf_warmup_days}d, train desde {wf_train_min.isoformat()})[/cyan]"
      )
      windows = generate_walk_forward_windows(
        split.full_start,
        split.full_end,
        earliest_train_start=wf_train_min,
      )
      report["steps"]["walk_forward_warmup"] = {
        "warmup_days": wf_warmup_days,
        "earliest_train_start": wf_train_min.isoformat(),
        "data_start": split.full_start.isoformat(),
      }
      report["steps"]["walk_forward_windows"] = [w.to_dict() for w in windows]
      oos_segments: list[OosSegmentResult] = []

      def _wf_backtest(timerange: str, params_file: Path, **kwargs) -> tuple[dict, str, Path]:
        return _backtest_with_params(
          strategy,
          timerange,
          params_file,
          enable_protections=enable_protections,
          allow_defaults=kwargs.get("allow_defaults", False),
        )

      # Inventario de adopciones (log explícito antes de ejecutar)
      adoption_plan: list = []
      for window in windows:
        decision = evaluate_wf_adoption(window, params_archive)
        adoption_plan.append(decision)
        if decision.adopted:
          console.print(
            f"[dim]    WF ventana {window.index} — adoptable: {decision.reason}[/dim]"
          )
        elif decision.source:
          console.print(
            f"[yellow]    WF ventana {window.index} — descartada: {decision.reason}[/yellow]"
          )

      ck_payload_base = {
        "run_id": run_id,
        "strategy": strategy,
        "baseline_oos": baseline_oos,
        "completed_seeds": sorted(completed_seeds),
        "seed_results": [asdict(s) for s in seed_results],
        "seed_params_raw": seed_params_raw,
      }
      if checkpoint and checkpoint.get("wf_windows_completed"):
        ck_payload_base["wf_windows_completed"] = list(checkpoint["wf_windows_completed"])

      for window in windows:
        record, adopt_decision = adopt_or_recover_wf_window(
          window,
          params_archive,
          backtest=_wf_backtest,
          enable_protections=enable_protections,
        )
        if record is not None:
          console.print(
            f"[dim]==> WF ventana {window.index} — completada "
            f"({'recuperada' if record.recovered else 'checkpoint/disco'}), omitiendo[/dim]"
          )
          is_profits_wf.append(float(record.is_metrics.get("profit_total_abs") or 0))
          seg = record.to_segment()
          oos_segments.append(seg)
          oos_profits_wf.append(seg.profit_abs)
          ck_payload_base["wf_windows_completed"] = merge_checkpoint_wf_completed(
            ck_payload_base, record
          )
          _save_checkpoint(run_path, ck_payload_base)
          touch_lock_heartbeat()
          continue

        if adopt_decision.source and not adopt_decision.adopted:
          console.print(
            f"[yellow]    ventana {window.index}: no adoptada — {adopt_decision.reason}[/yellow]"
          )

        wf_label = f"wf{window.index}_train"
        wf_ctx = f"{wf_label} seed=42"
        console.print(f"    ventana {window.index}: train {window.train_timerange}")
        archived, _ = _hyperopt_and_archive(
          strategy,
          window.train_timerange,
          epochs=wf_epochs_n,
          seed=42,
          enable_protections=enable_protections,
          archive_dir=params_archive,
          label=wf_label,
          min_trades=min_trades_n,
          spaces=opt_spaces,
          adopt_partial=False,
          context=wf_ctx,
          archive_extra_meta={
            "hyperopt_timerange": window.train_timerange,
            "test_timerange": window.test_timerange,
            "wf_window": window.index,
          },
        )
        is_m, _, _ = _backtest_with_params(
          strategy,
          window.train_timerange,
          archived,
          enable_protections=enable_protections,
          allow_defaults=False,
        )
        is_profits_wf.append(float(is_m.get("profit_total_abs") or 0))

        console.print(f"    ventana {window.index}: test {window.test_timerange}")
        oos_m, _, _ = _backtest_with_params(
          strategy,
          window.test_timerange,
          archived,
          enable_protections=enable_protections,
          allow_defaults=False,
        )
        clear_strategy_params(strategy)

        finished = WfWindowRecord(
          window=window.index,
          train=window.train_timerange,
          test=window.test_timerange,
          params_file=str(archived),
          is_metrics=is_m,
          oos_metrics=oos_m,
          completed_at=datetime.now(timezone.utc).isoformat(),
          recovered=False,
        )
        save_wf_segment(params_archive, finished)

        seg = finished.to_segment()
        oos_segments.append(seg)
        oos_profits_wf.append(seg.profit_abs)
        ck_payload_base["wf_windows_completed"] = merge_checkpoint_wf_completed(
          ck_payload_base, finished
        )
        _save_checkpoint(run_path, ck_payload_base)
        touch_lock_heartbeat()

      stitched = stitch_oos_equity(oos_segments)
      wfe_value = walk_forward_efficiency(is_profits_wf, oos_profits_wf)
      report["steps"]["walk_forward_stitched"] = stitched
      report["steps"]["walk_forward_efficiency"] = wfe_value

    record_step_git(report, "verdict")
    touch_lock_heartbeat()

    # Veredicto
    verdict_out = compute_verdict(
      VerdictInput(
        strategy=strategy,
        baseline_oos_metrics=baseline_oos,
        seed_results=seed_results,
        walk_forward_efficiency=wfe_value,
        max_param_divergence=max_div,
      )
    )
    report["verdict"] = verdict_out.verdict.value
    report["reasons"] = verdict_out.reasons
    report["verdict_details"] = verdict_out.details

    _write_report(run_path, report)
    _print_summary(report, seed_results, verdict_out.verdict, verdict_out.reasons)

    if verdict_out.verdict == Verdict.SOBREAJUSTADA:
      raise typer.Exit(code=2)


def _write_report(run_path: Path, report: dict) -> None:
  out = run_path / "report.json"
  out.write_text(json.dumps(report, indent=2), encoding="utf-8")
  console.print(f"[green]Reporte: {out}[/green]")


def _print_summary(
  report: dict,
  seeds: list[SeedRunResult],
  verdict: Verdict,
  reasons: list[str],
) -> None:
  table = Table(title=f"Veredicto {report['strategy']}: {verdict.value}")
  table.add_column("Semilla")
  table.add_column("IS Sharpe")
  table.add_column("OOS Sharpe")
  table.add_column("OOS PnL")
  for s in seeds:
    table.add_row(
      str(s.seed),
      f"{float(s.is_metrics.get('sharpe', 0)):.2f}",
      f"{float(s.oos_metrics.get('sharpe', 0)):.2f}",
      f"{float(s.oos_metrics.get('profit_total_abs', 0)):.0f}",
    )
  console.print(table)
  if reasons:
    console.print("[yellow]Motivos:[/yellow]")
    for r in reasons:
      console.print(f"  - {r}")


if __name__ == "__main__":
  typer.run(main)
