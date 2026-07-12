"""Resume granular de ventanas walk-forward (skip con validación de timerange)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from pathlib import Path
from typing import Callable

from pipeline.walk_forward import OosSegmentResult, WalkForwardWindow

BacktestFn = Callable[..., tuple[dict, str, Path]]


@dataclass(frozen=True)
class WfAdoptionDecision:
  window_index: int
  adopted: bool
  reason: str
  source: str | None = None


@dataclass
class WfWindowRecord:
  window: int
  train: str
  test: str
  params_file: str
  is_metrics: dict
  oos_metrics: dict
  completed_at: str
  recovered: bool = False

  def to_segment(self) -> OosSegmentResult:
    oos = self.oos_metrics
    return OosSegmentResult(
      window_index=self.window,
      profit_ratio=float(oos.get("profit_total") or 0),
      profit_abs=float(oos.get("profit_total_abs") or 0),
      trades=int(oos.get("trades") or 0),
      sharpe=float(oos.get("sharpe") or 0),
      starting_capital=0.0,
      ending_capital=0.0,
    )

  def to_checkpoint_entry(self) -> dict:
    return {
      "window": self.window,
      "train": self.train,
      "test": self.test,
      "params_file": self.params_file,
      "completed_at": self.completed_at,
      "recovered": self.recovered,
    }


def wf_segment_path(params_dir: Path, window_index: int) -> Path:
  return params_dir / f"wf{window_index}.json"


def wf_train_params_path(params_dir: Path, window_index: int) -> Path:
  return params_dir / f"wf{window_index}_train.json"


def wf_train_meta_path(params_dir: Path, window_index: int) -> Path:
  return params_dir / f"wf{window_index}_train.meta.json"


def timeranges_match_window(
  window: WalkForwardWindow,
  *,
  train: str,
  test: str,
) -> bool:
  return train == window.train_timerange and test == window.test_timerange


def _read_meta(meta_path: Path) -> dict:
  if not meta_path.is_file():
    return {}
  return json.loads(meta_path.read_text(encoding="utf-8"))


def _stored_train_timerange(meta: dict) -> str | None:
  for key in ("hyperopt_timerange", "train_timerange"):
    val = meta.get(key)
    if isinstance(val, str) and val.strip():
      return val.strip()
  return None


def load_wf_segment(params_dir: Path, window_index: int) -> WfWindowRecord | None:
  path = wf_segment_path(params_dir, window_index)
  if not path.is_file():
    return None
  data = json.loads(path.read_text(encoding="utf-8"))
  return WfWindowRecord(
    window=int(data["window"]),
    train=str(data["train"]),
    test=str(data["test"]),
    params_file=str(data["params_file"]),
    is_metrics=dict(data.get("is_metrics") or {}),
    oos_metrics=dict(data.get("oos_metrics") or {}),
    completed_at=str(data.get("completed_at") or ""),
    recovered=bool(data.get("recovered")),
  )


def save_wf_segment(params_dir: Path, record: WfWindowRecord) -> Path:
  path = wf_segment_path(params_dir, record.window)
  payload = {
    **asdict(record),
    "is_profit_abs": float(record.is_metrics.get("profit_total_abs") or 0),
  }
  path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
  return path


def evaluate_wf_adoption(
  window: WalkForwardWindow,
  params_dir: Path,
) -> WfAdoptionDecision:
  """Solo evalúa adoptabilidad (sin Docker)."""
  seg = load_wf_segment(params_dir, window.index)
  if seg is not None:
    if timeranges_match_window(window, train=seg.train, test=seg.test):
      return WfAdoptionDecision(
        window.index,
        True,
        f"segment wf{window.index}.json timerange OK",
        source=str(wf_segment_path(params_dir, window.index)),
      )
    return WfAdoptionDecision(
      window.index,
      False,
      (
        f"segment wf{window.index}.json timerange no coincide "
        f"(tiene train={seg.train} test={seg.test}, "
        f"plan train={window.train_timerange} test={window.test_timerange})"
      ),
      source=str(wf_segment_path(params_dir, window.index)),
    )

  train_path = wf_train_params_path(params_dir, window.index)
  if not train_path.is_file():
    return WfAdoptionDecision(
      window.index,
      False,
      "sin wf segment ni wf_train params en disco",
    )

  meta = _read_meta(wf_train_meta_path(params_dir, window.index))
  stored_train = _stored_train_timerange(meta)
  if stored_train is not None:
    if stored_train != window.train_timerange:
      return WfAdoptionDecision(
        window.index,
        False,
        (
          f"wf{window.index}_train.meta timerange rechazado "
          f"(meta={stored_train}, plan={window.train_timerange})"
        ),
        source=str(train_path),
      )
    return WfAdoptionDecision(
      window.index,
      False,
      "wf_train params OK en meta pero falta segment (requiere recuperación por backtest)",
      source=str(train_path),
    )

  return WfAdoptionDecision(
    window.index,
    False,
    "wf_train legacy sin hyperopt_timerange en meta — requiere recuperación por backtest",
    source=str(train_path),
  )


def adopt_or_recover_wf_window(
  window: WalkForwardWindow,
  params_dir: Path,
  *,
  backtest: BacktestFn,
  enable_protections: bool,
) -> tuple[WfWindowRecord | None, WfAdoptionDecision]:
  """
  Carga segment válido o recupera desde wf_train (backtest IS+OOS en timeranges del plan).

  Devuelve (record, decision). record solo si adopción/recuperación exitosa.
  """
  seg_path = wf_segment_path(params_dir, window.index)
  if seg_path.is_file():
    decision = evaluate_wf_adoption(window, params_dir)
    seg = load_wf_segment(params_dir, window.index)
    if decision.adopted and seg is not None:
      return seg, decision
    return None, decision

  decision = evaluate_wf_adoption(window, params_dir)
  train_path = wf_train_params_path(params_dir, window.index)
  if not train_path.is_file():
    return None, decision

  meta = _read_meta(wf_train_meta_path(params_dir, window.index))
  stored_train = _stored_train_timerange(meta)
  if stored_train is not None and stored_train != window.train_timerange:
    return None, decision

  # Recuperación: params en disco + backtest en timeranges del plan actual
  _ = enable_protections
  is_m, _, _ = backtest(
    window.train_timerange,
    train_path,
    enable_protections=enable_protections,
    allow_defaults=False,
  )
  oos_m, _, _ = backtest(
    window.test_timerange,
    train_path,
    enable_protections=enable_protections,
    allow_defaults=False,
  )
  record = WfWindowRecord(
    window=window.index,
    train=window.train_timerange,
    test=window.test_timerange,
    params_file=str(train_path),
    is_metrics=is_m,
    oos_metrics=oos_m,
    completed_at=datetime.now(timezone.utc).isoformat(),
    recovered=True,
  )
  save_wf_segment(params_dir, record)
  recover_decision = WfAdoptionDecision(
    window.index,
    True,
    "recuperada desde wf_train por backtest (plan timerange)",
    source=str(train_path),
  )
  return record, recover_decision


def merge_checkpoint_wf_completed(checkpoint: dict | None, record: WfWindowRecord) -> list[dict]:
  existing = list((checkpoint or {}).get("wf_windows_completed") or [])
  by_window = {int(e["window"]): e for e in existing}
  by_window[record.window] = record.to_checkpoint_entry()
  return [by_window[k] for k in sorted(by_window)]


def wf_completed_indices(checkpoint: dict | None, params_dir: Path, windows: list[WalkForwardWindow]) -> set[int]:
  """Índices adoptables según checkpoint + segmentos en disco."""
  out: set[int] = set()
  for w in windows:
    d = evaluate_wf_adoption(w, params_dir)
    if d.adopted:
      out.add(w.index)
  ck = (checkpoint or {}).get("wf_windows_completed") or []
  for entry in ck:
    idx = int(entry["window"])
    seg = load_wf_segment(params_dir, idx)
    plan = next((x for x in windows if x.index == idx), None)
    if plan and seg and timeranges_match_window(plan, train=seg.train, test=seg.test):
      out.add(idx)
  return out
