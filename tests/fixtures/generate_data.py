"""
Genera fixtures OHLCV con segmentos BULL y RANGE deliberados para integración CI.

- BULL (~2024-01-10 → 2024-02-25): tendencia sostenida en BTC/ETH (todos los TFs).
  Objetivo: EMA200 + ADX >= 25 en BTC/4h → btc_market_regime == BULL.
- RANGE (~2024-02-15 → 2024-03-18): lateral con baja direccionalidad.
  Objetivo: ADX < 25 en BTC/4h → btc_market_regime == RANGE (MeanRevBB).

Además inyecta patrones que disparan entradas reales de TrendRider, BreakoutVol y MeanRevBB
(pullbacks con RSI moderado, rupturas con pico de volumen, dips sobreventa en 15m).

Ejecutar: python tests/fixtures/generate_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FIXTURE_DIR = Path(__file__).resolve().parent / "data" / "binance"
USERDATA_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "user_data" / "fixtures" / "data" / "binance"
PAIRS = ["BTC_USDT", "ETH_USDT"]
TIMEFRAMES = {
  "1h": 7500,
  "4h": 1900,
  "15m": 32000,
}
BASE_PRICES = {"BTC_USDT": 42000.0, "ETH_USDT": 2200.0}
FREQ_MAP = {"1h": "1h", "4h": "4h", "15m": "15min"}
START_DATE = "2023-06-01"
RNG = np.random.default_rng(42)

# Ventanas alineadas al timerange de integración 20240101-20240320
BULL_START = pd.Timestamp("2024-01-10", tz="UTC")
BULL_END = pd.Timestamp("2024-02-25", tz="UTC")
RANGE_START = pd.Timestamp("2024-02-15", tz="UTC")
RANGE_END = pd.Timestamp("2024-03-18", tz="UTC")

# Drift por vela en segmento BULL (compuesto) — moderado para no saturar RSI
DRIFT_PER_BAR = {"1h": 0.0012, "4h": 0.0048, "15m": 0.0003}

# Cadencia de patrones de entrada por timeframe operativo
BULL_PATTERN_STEP = {"1h": 48, "15m": 192}
RANGE_OVERSOLD_STEP = {"15m": 96}

# Ventana DCA: caída escalonada en BULL para GridDCA (1h)
DCA_GRID_START = pd.Timestamp("2024-01-22 10:00", tz="UTC")
DCA_DROP_PER_BAR = 0.05


def _base_ohlcv(base_price: float, n: int, freq: str) -> pd.DataFrame:
  dates = pd.date_range(START_DATE, periods=n, freq=freq, tz="UTC")
  returns = RNG.normal(0, 0.0015, n)
  close = base_price * np.cumprod(1 + returns)
  high = close * (1 + RNG.uniform(0.0005, 0.004, n))
  low = close * (1 - RNG.uniform(0.0005, 0.004, n))
  open_ = np.roll(close, 1)
  open_[0] = base_price
  volume = RNG.uniform(800, 1200, n)
  return pd.DataFrame(
    {
      "date": dates,
      "open": open_,
      "high": high,
      "low": low,
      "close": close,
      "volume": volume,
    }
  )


def _mask_between(dates: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> np.ndarray:
  dt = pd.to_datetime(dates, utc=True)
  return ((dt >= start) & (dt <= end)).to_numpy()


def _set_bar(df: pd.DataFrame, i: int, o: float, h: float, l: float, c: float, vol: float) -> None:
  df.loc[i, "open"] = o
  df.loc[i, "high"] = h
  df.loc[i, "low"] = l
  df.loc[i, "close"] = c
  df.loc[i, "volume"] = vol


def inject_bull_trend(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
  """Tendencia alcista sostenida — eleva ADX y precio por encima de EMA200."""
  df = df.copy()
  drift = DRIFT_PER_BAR[timeframe]
  mask = _mask_between(df["date"], BULL_START, BULL_END)
  if not mask.any():
    return df

  idx = np.where(mask)[0]
  start_i = int(idx[0])
  anchor = float(df.loc[start_i - 1, "close"]) if start_i > 0 else float(df.loc[0, "close"])

  for j, i in enumerate(idx):
    price = anchor * ((1 + drift) ** (j + 1))
    wiggle = 1 + RNG.uniform(-0.001, 0.002)
    c = price * wiggle
    o = anchor * ((1 + drift) ** j) if j > 0 else float(df.loc[i, "open"])
    h = max(o, c) * (1 + RNG.uniform(0.001, 0.006))
    l = min(o, c) * (1 - RNG.uniform(0.0005, 0.003))
    _set_bar(df, i, o, h, l, c, float(RNG.uniform(1800, 2800)))

  if idx[-1] + 1 < len(df):
    last_close = float(df.loc[idx[-1], "close"])
    tail = df.loc[idx[-1] + 1 :].copy()
    scale = last_close / float(tail.iloc[0]["close"])
    for col in ("open", "high", "low", "close"):
      tail[col] = tail[col] * scale
    df.loc[idx[-1] + 1 :, ["open", "high", "low", "close"]] = tail[
      ["open", "high", "low", "close"]
    ].values

  return df


def inject_bull_entry_patterns(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
  """
  Pullback corto + recuperación con pico de volumen.
  Objetivo: TrendRider (RSI < 72, ADX alto, vol > 1.5× media) y BreakoutVol (ruptura + volumen).
  """
  if timeframe not in BULL_PATTERN_STEP:
    return df

  df = df.copy()
  mask = _mask_between(df["date"], BULL_START, BULL_END)
  idx = np.where(mask)[0]
  if len(idx) < 20:
    return df

  step = BULL_PATTERN_STEP[timeframe]
  for pos in range(int(idx[0]) + 30, int(idx[-1]) - 8, step):
  # Fase 1: volumen bajo (facilita umbral relativo en BreakoutVol)
    for k in range(4):
      i = pos + k
      if i >= len(df):
        break
      prev_c = float(df.loc[i - 1, "close"])
      drop = prev_c * (1 - 0.0035 * (k + 1))
      o = prev_c
      c = drop
      h = max(o, c) * 1.0008
      l = min(o, c) * 0.999
      _set_bar(df, i, o, h, l, c, float(RNG.uniform(900, 1200)))

    # Fase 2: ruptura con volumen elevado (señal enter_long en esta vela)
    i = pos + 4
    if i >= len(df):
      break
    base = float(df.loc[i - 1, "close"])
    prior_high = float(df.loc[max(0, i - 25) : i - 1, "high"].max())
    c = max(base * 1.012, prior_high * 1.006)
    o = base
    h = c * 1.004
    l = min(o, base * 0.998)
    _set_bar(df, i, o, h, l, c, float(RNG.uniform(6500, 9000)))

    # Fase 3: vela siguiente con mínimo <= cierre de señal — permite fill de orden limit
    i_fill = i + 1
    if i_fill < len(df):
      limit_px = c
      o_fill = limit_px * 1.0005
      l_fill = limit_px * 0.994
      c_fill = limit_px * 0.997
      h_fill = max(o_fill, c_fill) * 1.0008
      _set_bar(df, i_fill, o_fill, h_fill, l_fill, c_fill, float(RNG.uniform(2000, 3500)))

  return df


def inject_range_chop(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
  """Oscilación lateral — ADX bajo, precio cerca de EMA200."""
  df = df.copy()
  mask = _mask_between(df["date"], RANGE_START, RANGE_END)
  if not mask.any():
    return df

  idx = np.where(mask)[0]
  center = float(df.loc[idx[0], "close"])
  amp = center * 0.010

  for k, i in enumerate(idx):
    phase = k * 0.35
    c = center + amp * np.sin(phase) + RNG.normal(0, center * 0.0008)
    o = c * (1 + RNG.uniform(-0.0005, 0.0005))
    h = max(o, c) * (1 + RNG.uniform(0.0003, 0.002))
    l = min(o, c) * (1 - RNG.uniform(0.0003, 0.002))
    _set_bar(df, i, o, h, l, c, float(RNG.uniform(600, 1100)))

  return df


def inject_range_oversold_dips(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
  """Dips pronunciados en RANGE para MeanRevBB (RSI bajo + cierre bajo banda inferior)."""
  if timeframe not in RANGE_OVERSOLD_STEP:
    return df

  df = df.copy()
  mask = _mask_between(df["date"], RANGE_START, RANGE_END)
  idx = np.where(mask)[0]
  if len(idx) < 20:
    return df

  step = RANGE_OVERSOLD_STEP[timeframe]
  for pos in range(int(idx[0]) + 40, int(idx[-1]) - 6, step):
    anchor = float(df.loc[pos - 1, "close"])
    for k in range(3):
      i = pos + k
      if i >= len(df):
        break
      drop_pct = 0.008 + 0.004 * k
      c = anchor * (1 - drop_pct)
      o = float(df.loc[i - 1, "close"])
      l = c * 0.997
      h = max(o, c) * 1.001
      _set_bar(df, i, o, h, l, c, float(RNG.uniform(1400, 2200)))

  return df


def inject_grid_dca_drawdown(df: pd.DataFrame, timeframe: str, pair: str = "") -> pd.DataFrame:
  """
  Caída escalonada en BULL (1h, BTC) — dispara entrada + hasta 3 DCA y luego stop.
  Objetivo: grid_dca_check con --min-position-adjustments 3 en ventana DCA.
  """
  if timeframe != "1h" or pair != "BTC_USDT":
    return df

  df = df.copy()
  dates = pd.to_datetime(df["date"], utc=True)
  idx = int(dates.searchsorted(DCA_GRID_START))
  if idx < 12 or idx + 6 >= len(df):
    return df

  bull_mask = _mask_between(df["date"], BULL_START, BULL_END)
  if not bull_mask[idx]:
    return df

  base = float(df.loc[idx - 1, "close"])
  # Vela de entrada: dip leve (RSI < umbral GridDCA)
  c0 = base * 0.992
  o0 = base
  _set_bar(df, idx, o0, max(o0, c0) * 1.001, c0 * 0.998, c0, float(RNG.uniform(2000, 3000)))

  prev = c0
  # 8 velas de caída: 3 DCA + margen para disparar stop -22% sobre precio promediado
  for k in range(1, 9):
    i = idx + k
    if i >= len(df):
      break
    prev = prev * (1 - DCA_DROP_PER_BAR)
    o = float(df.loc[i - 1, "close"])
    _set_bar(df, i, o, o * 1.0005, prev * 0.997, prev, float(RNG.uniform(1500, 2200)))

  return df


def generate_pair_timeframe(pair: str, timeframe: str, n: int) -> pd.DataFrame:
  df = _base_ohlcv(BASE_PRICES[pair], n, FREQ_MAP[timeframe])
  df = inject_bull_trend(df, timeframe)
  df = inject_bull_entry_patterns(df, timeframe)
  df = inject_range_chop(df, timeframe)
  df = inject_range_oversold_dips(df, timeframe)
  df = inject_grid_dca_drawdown(df, timeframe, pair)
  return df


def validate_regime_windows() -> None:
  """Verifica que BTC/4h tenga BULL y RANGE en las ventanas esperadas."""
  import sys

  root = Path(__file__).resolve().parents[2]
  sys.path.insert(0, str(root / "user_data" / "strategies"))
  from _base import QuantBaseStrategy  # noqa: E402
  from quant_core import MarketRegime  # noqa: E402

  btc_4h = pd.read_feather(FIXTURE_DIR / "BTC_USDT-4h.feather")
  labeled = QuantBaseStrategy.add_regime_indicators(btc_4h.copy())
  dates = pd.to_datetime(labeled["date"], utc=True)

  bull_mask = (dates >= BULL_START) & (dates <= BULL_END)
  range_mask = (dates >= RANGE_START) & (dates <= RANGE_END)

  bull_labels = labeled.loc[bull_mask, "market_regime"]
  range_labels = labeled.loc[range_mask, "market_regime"]

  bull_ratio = (bull_labels == MarketRegime.BULL.value).mean()
  range_ratio = (range_labels == MarketRegime.RANGE.value).mean()

  print(f"BTC/4h BULL window: {bull_ratio:.1%} velas BULL (objetivo >= 60%)")
  print(f"BTC/4h RANGE window: {range_ratio:.1%} velas RANGE (objetivo >= 50%)")

  if bull_ratio < 0.6:
    raise SystemExit(f"Fixture BULL insuficiente: {bull_ratio:.1%}")
  if range_ratio < 0.5:
    raise SystemExit(f"Fixture RANGE insuficiente: {range_ratio:.1%}")


def validate_entry_signals() -> None:
  """Cuenta señales enter_long con el pipeline real de Freqtrade (incl. @informative)."""
  import sys

  from freqtrade.configuration import Configuration
  from freqtrade.enums import RunMode
  from freqtrade.exchange import Exchange
  from freqtrade.optimize.backtesting import Backtesting
  from freqtrade.resolvers import StrategyResolver

  root = Path(__file__).resolve().parents[2]
  sys.path.insert(0, str(root / "user_data" / "strategies"))

  def _count_signals(strategy_name: str, timerange: str, pair_file: str, tf: str) -> int:
    config = Configuration.from_files(
      [
        str(root / "user_data/config/base.json"),
        str(root / "user_data/config/backtest.json"),
        str(root / "user_data/config/backtest_fixtures.json"),
      ]
    )
    if hasattr(config, "get_config"):
      config = config.get_config()
    config["runmode"] = RunMode.BACKTEST
    config["strategy"] = strategy_name
    config["strategy_path"] = str(root / "user_data/strategies")
    config["timerange"] = timerange
    config["datadir"] = FIXTURE_DIR
    config["exchange"]["pair_whitelist"] = ["BTC/USDT", "ETH/USDT"]

    exchange = Exchange(config)
    strategy = StrategyResolver.load_strategy(config)
    strategy.ft_load_hyper_params(False)
    bt = Backtesting(config, exchange)
    bt._set_strategy(strategy)
    data, _ = bt.load_bt_data()
    pair = "BTC/USDT"
    df = data[pair]
    df = strategy.advise_indicators(df.copy(), {"pair": pair})
    df = strategy.advise_entry(df, {"pair": pair})
    dates = pd.to_datetime(df["date"], utc=True)
    t0 = f"{timerange[:4]}-{timerange[4:6]}-{timerange[6:8]}"
    t1 = f"{timerange[9:13]}-{timerange[13:15]}-{timerange[15:17]}"
    window = (dates >= t0) & (dates <= t1)
    return int(df.loc[window, "enter_long"].fillna(0).sum())

  trend_signals = _count_signals("TrendRider", "20240115-20240228", "BTC_USDT-1h.feather", "1h")
  breakout_signals = _count_signals("BreakoutVol", "20240115-20240228", "BTC_USDT-1h.feather", "1h")
  meanrev_signals = _count_signals("MeanRevBB", "20240215-20240318", "BTC_USDT-15m.feather", "15m")

  print(f"TrendRider enter_long (pipeline FT): {trend_signals} (objetivo >= 3)")
  print(f"BreakoutVol enter_long (pipeline FT): {breakout_signals} (objetivo >= 3)")
  print(f"MeanRevBB enter_long (pipeline FT): {meanrev_signals} (objetivo >= 3)")

  if trend_signals < 3:
    raise SystemExit(f"Fixture TrendRider insuficiente: {trend_signals} señales")
  if breakout_signals < 3:
    raise SystemExit(f"Fixture BreakoutVol insuficiente: {breakout_signals} señales")
  if meanrev_signals < 3:
    raise SystemExit(f"Fixture MeanRevBB insuficiente: {meanrev_signals} señales")


def write_fixtures_skip_validate() -> None:
  """Escribe fixtures sin validar (entorno local sin TA-Lib)."""
  for target_dir in (FIXTURE_DIR, USERDATA_FIXTURE_DIR):
    target_dir.mkdir(parents=True, exist_ok=True)
    for pair in PAIRS:
      for timeframe, n in TIMEFRAMES.items():
        df = generate_pair_timeframe(pair, timeframe, n)
        path = target_dir / f"{pair}-{timeframe}.feather"
        df.to_feather(path)
        print(f"Wrote {path} ({len(df)} candles)")


def write_fixtures() -> None:
  FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
  USERDATA_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
  for pair in PAIRS:
    for timeframe, n in TIMEFRAMES.items():
      df = generate_pair_timeframe(pair, timeframe, n)
      for target_dir in (FIXTURE_DIR, USERDATA_FIXTURE_DIR):
        path = target_dir / f"{pair}-{timeframe}.feather"
        df.to_feather(path)
        print(f"Wrote {path} ({len(df)} candles, {df['date'].iloc[0]} -> {df['date'].iloc[-1]})")
  validate_regime_windows()
  validate_entry_signals()
  print("Fixture regime + entry signal validation OK")


if __name__ == "__main__":
  try:
    write_fixtures()
  except ModuleNotFoundError as exc:
    if "talib" in str(exc):
      print("WARN: TA-Lib no disponible — escribiendo sin validar. Usar scripts/regenerate_fixtures.ps1")
      write_fixtures_skip_validate()
    else:
      raise
