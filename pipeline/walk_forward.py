"""Walk-forward 12m train / 3m test / paso 3m y stitching OOS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from dateutil.relativedelta import relativedelta

from pipeline.timerange_split import format_timerange


@dataclass(frozen=True)
class WalkForwardWindow:
  index: int
  train_start: date
  train_end: date
  test_start: date
  test_end: date

  @property
  def train_timerange(self) -> str:
    return format_timerange(self.train_start, self.train_end)

  @property
  def test_timerange(self) -> str:
    return format_timerange(self.test_start, self.test_end)

  def to_dict(self) -> dict:
    return {
      "index": self.index,
      "train_start": self.train_start.isoformat(),
      "train_end": self.train_end.isoformat(),
      "test_start": self.test_start.isoformat(),
      "test_end": self.test_end.isoformat(),
      "train_timerange": self.train_timerange,
      "test_timerange": self.test_timerange,
    }


def generate_walk_forward_windows(
  data_start: date,
  data_end: date,
  *,
  earliest_train_start: date | None = None,
  train_months: int = 12,
  test_months: int = 3,
  step_months: int = 3,
) -> list[WalkForwardWindow]:
  """
  Genera ventanas rodantes mientras el tramo test cabe en ``data_end``.

  ``earliest_train_start``: primer train_start permitido (p. ej. ``data_start + warmup``).
  Si es posterior a ``data_start``, la ventana 0 se desplaza — no se entrena sin warmup.
  """
  windows: list[WalkForwardWindow] = []
  train_start = earliest_train_start or data_start
  if train_start < data_start:
    train_start = data_start
  idx = 0

  while True:
    train_end = train_start + relativedelta(months=train_months) - relativedelta(days=1)
    test_start = train_end + relativedelta(days=1)
    test_end = test_start + relativedelta(months=test_months) - relativedelta(days=1)

    if test_end > data_end:
      break
    if train_end >= test_start:
      break

    windows.append(
      WalkForwardWindow(
        index=idx,
        train_start=train_start,
        train_end=train_end,
        test_start=test_start,
        test_end=test_end,
      )
    )
    idx += 1
    train_start = train_start + relativedelta(months=step_months)

  return windows


@dataclass
class OosSegmentResult:
  window_index: int
  profit_ratio: float
  profit_abs: float
  trades: int
  sharpe: float
  starting_capital: float
  ending_capital: float


def stitch_oos_equity(
  segments: list[OosSegmentResult],
  initial_capital: float = 10_000.0,
) -> dict:
  """
  Concatena tramos OOS: capital final de cada ventana = inicial de la siguiente.

  No re-backtestea el período completo — solo encadena ratios de cada test.
  """
  capital = initial_capital
  curve: list[dict] = []
  total_profit_abs = 0.0

  for seg in segments:
    ending = capital * (1.0 + seg.profit_ratio)
    profit_abs = ending - capital
    total_profit_abs += profit_abs
    curve.append(
      {
        "window_index": seg.window_index,
        "starting_capital": capital,
        "ending_capital": ending,
        "profit_ratio": seg.profit_ratio,
        "profit_abs": profit_abs,
        "trades": seg.trades,
        "sharpe": seg.sharpe,
      }
    )
    capital = ending

  total_return = (capital - initial_capital) / initial_capital if initial_capital else 0.0
  return {
    "initial_capital": initial_capital,
    "final_capital": capital,
    "total_return": total_return,
    "total_profit_abs": total_profit_abs,
    "segments": curve,
  }


def walk_forward_efficiency(is_profits: list[float], oos_profits: list[float]) -> float:
  """WFE = beneficio OOS cosido / beneficio IS agregado (hyperopt por ventana)."""
  is_total = sum(is_profits)
  oos_total = sum(oos_profits)
  if is_total <= 0:
    return 0.0 if oos_total <= 0 else float("inf")
  return oos_total / is_total
