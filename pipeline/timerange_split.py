"""Corte IS/OOS con fechas absolutas auditables (70/30 por días de calendario)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

IS_RATIO = 0.70


@dataclass(frozen=True)
class IsOosSplit:
  """Fechas absolutas — no re-evaluar porcentajes en pasos posteriores."""

  full_timerange: str
  full_start: date
  full_end: date
  is_start: date
  is_end: date
  oos_start: date
  oos_end: date
  is_timerange: str
  oos_timerange: str
  is_ratio: float = IS_RATIO

  def to_dict(self) -> dict:
    return {
      **asdict(self),
      "full_start": self.full_start.isoformat(),
      "full_end": self.full_end.isoformat(),
      "is_start": self.is_start.isoformat(),
      "is_end": self.is_end.isoformat(),
      "oos_start": self.oos_start.isoformat(),
      "oos_end": self.oos_end.isoformat(),
    }


def _parse_bound(raw: str, *, end_of_day: bool) -> date:
  text = raw.strip()
  if len(text) != 8 or not text.isdigit():
    raise ValueError(f"Fecha inválida (esperado YYYYMMDD): {raw}")
  y, m, d = int(text[0:4]), int(text[4:6]), int(text[6:8])
  return date(y, m, d)


def parse_timerange(timerange: str) -> tuple[date, date]:
  """Parsea ``YYYYMMDD-YYYYMMDD`` o ``YYYYMMDD-`` (fin = última vela disponible)."""
  if "-" not in timerange:
    raise ValueError(f"timerange inválido: {timerange}")
  start_raw, end_raw = timerange.split("-", 1)
  start = _parse_bound(start_raw, end_of_day=False)
  if not end_raw:
    raise ValueError("timerange abierto requiere data_end explícito")
  end = _parse_bound(end_raw, end_of_day=True)
  if end < start:
    raise ValueError(f"timerange invertido: {timerange}")
  return start, end


def resolve_data_end(datadir: Path, pair: str = "BTC_USDT", timeframe: str = "1h") -> date:
  """Última fecha en feather de referencia."""
  path = datadir / f"{pair}-{timeframe}.feather"
  if not path.exists():
    raise FileNotFoundError(f"Sin datos de referencia: {path}")
  df = pd.read_feather(path, columns=["date"])
  last = pd.to_datetime(df["date"], utc=True).max()
  return last.date()


def format_timerange(start: date, end: date) -> str:
  return f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"


def compute_is_oos_split(
  timerange: str,
  *,
  data_end: date | None = None,
  is_ratio: float = IS_RATIO,
) -> IsOosSplit:
  """
  Calcula el corte 70/30 una sola vez.

  ``timerange`` puede terminar en ``-``; entonces ``data_end`` es obligatorio.
  """
  if timerange.endswith("-"):
    if data_end is None:
      raise ValueError("timerange abierto requiere data_end")
    start = _parse_bound(timerange[:-1], end_of_day=False)
    end = data_end
  else:
    start, end = parse_timerange(timerange)

  total_days = (end - start).days + 1
  if total_days < 90:
    raise ValueError(f"Ventana demasiado corta ({total_days} días) para IS/OOS")

  is_days = max(1, int(total_days * is_ratio))
  is_end = start + timedelta(days=is_days - 1)
  oos_start = is_end + timedelta(days=1)
  oos_end = end

  if oos_start > oos_end:
    raise ValueError("OOS vacío tras el corte IS/OOS")

  return IsOosSplit(
    full_timerange=format_timerange(start, end),
    full_start=start,
    full_end=end,
    is_start=start,
    is_end=is_end,
    oos_start=oos_start,
    oos_end=oos_end,
    is_timerange=format_timerange(start, is_end),
    oos_timerange=format_timerange(oos_start, oos_end),
    is_ratio=is_ratio,
  )
