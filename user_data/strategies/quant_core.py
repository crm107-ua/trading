"""Funciones puras de régimen, riesgo y validación de entrada (sin dependencias Freqtrade)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Callable

DEFAULT_ADX_TREND_THRESHOLD = 25.0
DEFAULT_MAX_SPREAD_RATIO = 0.003
DEFAULT_RISK_PER_TRADE = 0.01
DEFAULT_ATR_STOP_MULTIPLIER = 2.0
DEFAULT_ATR_TRAIL_MULTIPLIER = 1.0
DEFAULT_ATR_PERIOD = 14
BREAKEVEN_PROFIT_THRESHOLD = 0.02
TRAILING_PROFIT_THRESHOLD = 0.04
DEFAULT_CORRELATION_THRESHOLD = 0.8
DEFAULT_CORRELATION_LOOKBACK_DAYS = 30
DEFAULT_MIN_CORRELATION_OBSERVATIONS = 20
REGIME_EMA_PERIOD = 200
REGIME_INFORMATIVE_TIMEFRAME = "4h"
STARTUP_CANDLE_MARGIN = 50


class InformativeColumnNotFoundError(LookupError):
  """Columna fusionada de @informative ausente — no degradar a valores por defecto."""


def compute_startup_candle_count(
  strategy_timeframe: str,
  *,
  regime_ema_period: int = REGIME_EMA_PERIOD,
  regime_timeframe: str = REGIME_INFORMATIVE_TIMEFRAME,
  margin: int = STARTUP_CANDLE_MARGIN,
) -> int:
  """
  Velas de warmup en el timeframe de la estrategia.

  EMA200 en informative 4h ⇒ 200×4h = 800h de historia mínima.
  En 1h → 850 velas; en 15m → 3.250 velas (más margen ADX/ATR).
  """
  try:
    from freqtrade.exchange import timeframe_to_minutes

    base_min = timeframe_to_minutes(strategy_timeframe)
    regime_min = timeframe_to_minutes(regime_timeframe)
  except Exception:
    base_min = _timeframe_to_minutes_local(strategy_timeframe)
    regime_min = _timeframe_to_minutes_local(regime_timeframe)
  if base_min <= 0 or regime_min <= 0:
    return regime_ema_period * 4 + margin
  return int(regime_ema_period * (regime_min / base_min)) + margin


def _timeframe_to_prev_date_local(timeframe: str, current_time: "pd.Timestamp") -> "pd.Timestamp":
  """Fallback si Freqtrade no está disponible (tests unitarios)."""
  import pandas as pd

  tf = timeframe.strip().lower()
  ts = pd.Timestamp(current_time)
  if ts.tzinfo is None:
    ts = ts.tz_localize("UTC")
  if tf.endswith("m"):
    minutes = int(tf[:-1])
    return ts.floor(f"{minutes}min")
  if tf.endswith("h"):
    hours = int(tf[:-1])
    return ts.floor(f"{hours}h")
  if tf.endswith("d"):
    days = int(tf[:-1])
    return ts.floor(f"{days}d")
  raise ValueError(f"timeframe no soportado: {timeframe}")


def column_value_at_time(
  dataframe: "pd.DataFrame",
  column: str,
  current_time: datetime,
  timeframe: str,
) -> float | str | None:
  """
  Valor de columna en la vela causal de current_time — nunca iloc[-1] del histórico completo.

  Usa timeframe_to_prev_date (Freqtrade) para alinear la vela y devuelve la fila <= ese open.
  """
  import pandas as pd

  if dataframe is None or dataframe.empty or column not in dataframe.columns:
    return None
  if "date" not in dataframe.columns:
    return None

  try:
    from freqtrade.exchange import timeframe_to_prev_date

    candle_start = timeframe_to_prev_date(timeframe, pd.Timestamp(current_time))
  except Exception:
    candle_start = _timeframe_to_prev_date_local(timeframe, pd.Timestamp(current_time))

  dates = pd.to_datetime(dataframe["date"], utc=True)
  ct = pd.Timestamp(candle_start)
  if ct.tzinfo is None and dates.dt.tz is not None:
    ct = ct.tz_localize("UTC")

  exact = dataframe.loc[dates == ct]
  if not exact.empty:
    row = exact.iloc[-1]
  else:
    eligible = dataframe.loc[dates <= ct]
    if eligible.empty:
      return None
    row = eligible.iloc[-1]

  value = row[column]
  if value is None or (isinstance(value, float) and value != value):
    return None
  return value


def resolve_informative_column(
  columns: "pd.Index | list[str]",
  indicator: str,
  *,
  timeframe_suffix: str = "4h",
  required: bool = True,
) -> str | None:
  """Resuelve nombre de columna fusionada por @informative (varía según Freqtrade)."""
  direct = f"{indicator}_{timeframe_suffix}"
  col_list = list(columns)
  if direct in col_list:
    return direct
  suffix = f"{indicator}_{timeframe_suffix}"
  matches = [col for col in col_list if col.endswith(suffix)]
  if not matches:
    if required:
      raise InformativeColumnNotFoundError(
        f"No se encontró columna informative para '{indicator}' "
        f"(sufijo '{suffix}'). Columnas disponibles: {col_list}"
      )
    return None
  return sorted(matches)[0]


def compute_prior_rolling_max(values: "pd.Series", period: int) -> "pd.Series":
  """
  Máximo rolling de las N velas anteriores — excluye la vela actual (shift(1)).

  Ruptura válida: close > compute_prior_rolling_max(high, N), no high.rolling(N).max()
  sin shift (autocontaminación).
  """
  import pandas as pd

  if period <= 0:
    return pd.Series(dtype=float)
  return values.rolling(period).max().shift(1)


def compute_prior_rolling_mean(values: "pd.Series", period: int) -> "pd.Series":
  """
  Media rolling de las N velas anteriores — excluye la vela actual (shift(1)).

  Volumen de confirmación: la vela de ruptura se compara contra la media previa,
  no contra una media que incluye su propio volumen.
  """
  import pandas as pd

  if period <= 0:
    return pd.Series(dtype=float)
  return values.rolling(period).mean().shift(1)


def _timeframe_to_minutes_local(timeframe: str) -> int:
  """Fallback sin Freqtrade instalado (tests unitarios locales)."""
  tf = timeframe.strip().lower()
  if tf.endswith("m"):
    return int(tf[:-1])
  if tf.endswith("h"):
    return int(tf[:-1]) * 60
  if tf.endswith("d"):
    return int(tf[:-1]) * 1440
  raise ValueError(f"timeframe no soportado: {timeframe}")


class MarketRegime(str, Enum):
  BULL = "BULL"
  BEAR = "BEAR"
  RANGE = "RANGE"


def compute_market_regime(
  close: float,
  ema200: float,
  adx: float,
  adx_threshold: float = DEFAULT_ADX_TREND_THRESHOLD,
) -> MarketRegime:
  if adx < adx_threshold:
    return MarketRegime.RANGE
  if close > ema200:
    return MarketRegime.BULL
  return MarketRegime.BEAR


def compute_atr_stoploss_ratio(
  current_profit: float,
  atr: float,
  open_rate: float,
  current_rate: float,
  atr_stop_multiplier: float = DEFAULT_ATR_STOP_MULTIPLIER,
  atr_trail_multiplier: float = DEFAULT_ATR_TRAIL_MULTIPLIER,
  breakeven_threshold: float = BREAKEVEN_PROFIT_THRESHOLD,
  trailing_threshold: float = TRAILING_PROFIT_THRESHOLD,
  stoploss_from_open_fn: Callable[..., float] | None = None,
) -> float:
  if open_rate <= 0 or current_rate <= 0 or atr <= 0:
    return -0.10

  _sl_from_open = stoploss_from_open_fn or _default_stoploss_from_open

  if current_profit >= trailing_threshold:
    trail_distance = (atr_trail_multiplier * atr) / current_rate
    return min(trail_distance, 0.5)

  if current_profit >= breakeven_threshold:
    return _sl_from_open(0.0, current_profit, is_short=False)

  # Negativo respecto al precio de entrada = stop por debajo (long)
  initial_distance = -((atr_stop_multiplier * atr) / open_rate)
  return _sl_from_open(initial_distance, current_profit, is_short=False)


def _default_stoploss_from_open(
  open_relative: float, current_profit: float, is_short: bool = False
) -> float:
  """Replica simplificada de freqtrade.strategy.stoploss_from_open (long, sin leverage)."""
  if current_profit == -1 and not is_short:
    return 1.0
  if is_short:
    stoploss = -1 + ((1 - open_relative) / (1 - current_profit))
  else:
    stoploss = 1 - ((1 + open_relative) / (1 + current_profit))
  return max(stoploss, 0.0)


def compute_raw_risk_stake_amount(
  wallet_balance: float,
  atr: float,
  rate: float,
  risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
  atr_stop_multiplier: float = DEFAULT_ATR_STOP_MULTIPLIER,
) -> float:
  """Stake teórico para ~risk_per_trade sin aplicar límites del exchange."""
  if wallet_balance <= 0 or atr <= 0 or rate <= 0:
    return 0.0
  stop_distance_pct = (atr_stop_multiplier * atr) / rate
  if stop_distance_pct <= 0:
    return 0.0
  return (wallet_balance * risk_per_trade) / stop_distance_pct


def evaluate_min_stake_policy(
  raw_stake: float,
  min_stake: float | None,
  *,
  policy: str = "reject",
) -> tuple[float | None, bool, str]:
  """
  Resuelve el caso borde cuando el stake por riesgo 1% queda bajo el mínimo del exchange.

  Políticas:
  - reject: no abrir (riesgo real sería > 1% si se subiera al mínimo)
  - bump_to_min: usar min_stake aceptando riesgo elevado (debe loguearse)
  """
  if min_stake is None or raw_stake <= 0:
    return raw_stake, True, "ok"
  if raw_stake >= min_stake:
    return raw_stake, True, "ok"
  if policy == "bump_to_min":
    return min_stake, True, f"stake_elevado_al_minimo:raw={raw_stake:.2f}<min={min_stake:.2f}"
  return None, False, f"stake_bajo_minimo:raw={raw_stake:.2f}<min={min_stake:.2f}"


def compute_risk_stake_amount(
  wallet_balance: float,
  atr: float,
  rate: float,
  risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
  atr_stop_multiplier: float = DEFAULT_ATR_STOP_MULTIPLIER,
  min_stake: float | None = None,
  max_stake: float | None = None,
) -> float:
  """Compat: calcula stake aplicando límites min/max (legacy). Preferir raw + evaluate_min_stake_policy."""
  stake = compute_raw_risk_stake_amount(
    wallet_balance, atr, rate, risk_per_trade, atr_stop_multiplier
  )
  if min_stake is not None and stake > 0:
    stake = max(stake, min_stake)
  if max_stake is not None and stake > 0:
    stake = min(stake, max_stake)
  return stake


def evaluate_entry_confirmation(
  spread_ratio: float | None,
  regime: MarketRegime | None,
  side: str,
  *,
  max_spread_ratio: float = DEFAULT_MAX_SPREAD_RATIO,
  block_bear_longs: bool = True,
  block_bull_shorts: bool = True,
  high_volatility_event: bool = False,
  regime_filter_enabled: bool = True,
  spread_check_enabled: bool = True,
  stake_allowed: bool = True,
  stake_reason: str = "ok",
) -> tuple[bool, str]:
  if not stake_allowed:
    return False, stake_reason

  if high_volatility_event:
    return False, "evento_alta_volatilidad_pendiente"

  # spread_check_enabled=False en backtest (sin orderbook) — no evaluar spread
  if spread_check_enabled and spread_ratio is not None and spread_ratio > max_spread_ratio:
    return False, f"spread_alto:{spread_ratio:.4f}>{max_spread_ratio:.4f}"

  if regime_filter_enabled and regime is not None:
    if side == "long" and block_bear_longs and regime == MarketRegime.BEAR:
      return False, "regimen_BEAR_contradice_long"
    if side == "short" and block_bull_shorts and regime == MarketRegime.BULL:
      return False, "regimen_BULL_contradice_short"

  return True, "ok"


def extract_daily_returns(closes: "pd.Series", lookback_days: int = DEFAULT_CORRELATION_LOOKBACK_DAYS) -> "pd.Series":
  """Convierte cierres intradía a retornos diarios (últimos lookback_days)."""
  import pandas as pd

  if closes is None or closes.empty:
    return pd.Series(dtype=float)
  idx = pd.to_datetime(closes.index if isinstance(closes.index, pd.DatetimeIndex) else range(len(closes)))
  series = pd.Series(closes.values, index=idx).sort_index()
  daily = series.resample("1D").last().dropna()
  returns = daily.pct_change().dropna()
  if lookback_days > 0:
    returns = returns.tail(lookback_days)
  return returns


def pearson_correlation(
  returns_a: "pd.Series",
  returns_b: "pd.Series",
  min_observations: int = DEFAULT_MIN_CORRELATION_OBSERVATIONS,
) -> tuple[float | None, bool]:
  """Correlación de Pearson alineada por fecha. Retorna (valor, historial_suficiente)."""
  import pandas as pd

  if returns_a is None or returns_b is None or returns_a.empty or returns_b.empty:
    return None, False
  aligned = pd.concat([returns_a, returns_b], axis=1, join="inner").dropna()
  if len(aligned) < min_observations:
    return None, False
  corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
  if corr != corr:
    return None, False
  return corr, True


def count_high_correlations(
  candidate_returns: "pd.Series",
  open_pairs_returns: dict[str, "pd.Series"],
  threshold: float = DEFAULT_CORRELATION_THRESHOLD,
  min_observations: int = DEFAULT_MIN_CORRELATION_OBSERVATIONS,
) -> tuple[int, list[tuple[str, float]], list[str]]:
  """
  Cuenta pares abiertos con correlación > threshold respecto al candidato.
  Retorna (conteo_alto, pares_alto_detalle, pares_sin_datos).
  """
  high: list[tuple[str, float]] = []
  insufficient: list[str] = []
  for open_pair, open_returns in open_pairs_returns.items():
    corr, sufficient = pearson_correlation(
      candidate_returns, open_returns, min_observations
    )
    if not sufficient:
      insufficient.append(open_pair)
      continue
    if corr is not None and corr > threshold:
      high.append((open_pair, corr))
  return len(high), high, insufficient


# --- Máscaras de entrada/salida (funciones puras para estrategias y RegimeSwitcher) ---

TREND_ENTER_TAG = "trend"
MEAN_REV_ENTER_TAG = "mean_rev"
TREND_SIGNAL_EXIT_TAG = "trend_signal"
MEAN_REV_SIGNAL_EXIT_TAG = "mean_rev_signal"


def trend_rider_entry_mask(
  dataframe: "pd.DataFrame",
  *,
  adx_threshold: int = 25,
  rsi_max: int = 72,
  volume_factor: float = 1.5,
  btc_regime_col: str = "btc_market_regime",
) -> "pd.Series":
  """Entrada TrendRider: BULL + EMA rápida > lenta + ADX + RSI + volumen."""
  import pandas as pd

  if dataframe.empty:
    return pd.Series(dtype=bool)

  vol_threshold = dataframe["volume_mean"] * volume_factor
  bull_mask = dataframe[btc_regime_col] == MarketRegime.BULL.value
  return (
    bull_mask
    & (dataframe["ema_fast"] > dataframe["ema_slow"])
    & (dataframe["adx"] > adx_threshold)
    & (dataframe["rsi"] < rsi_max)
    & (dataframe["volume"] > vol_threshold)
    & (dataframe["volume"] > 0)
  )


def trend_rider_exit_mask(dataframe: "pd.DataFrame") -> "pd.Series":
  """TrendRider no usa señal de salida — solo trailing ATR de la base."""
  import pandas as pd

  return pd.Series(False, index=dataframe.index, dtype=bool)


def mean_rev_entry_mask(
  dataframe: "pd.DataFrame",
  *,
  rsi_threshold: int = 28,
  bb_offset: float = 0.0,
  require_range_regime: bool = True,
  btc_regime_col: str = "btc_market_regime",
) -> "pd.Series":
  """Entrada mean-rev: RANGE (opcional) + RSI bajo + cierre bajo banda inferior."""
  import pandas as pd

  if dataframe.empty:
    return pd.Series(dtype=bool)

  if require_range_regime:
    if btc_regime_col not in dataframe.columns:
      regime_mask = pd.Series(False, index=dataframe.index)
    else:
      regime_mask = dataframe[btc_regime_col] == MarketRegime.RANGE.value
  else:
    regime_mask = True

  bb_lower_threshold = dataframe["bb_lower"] * (1 + bb_offset)
  return (
    regime_mask
    & (dataframe["rsi"] < rsi_threshold)
    & (dataframe["close"] < bb_lower_threshold)
    & (dataframe["volume"] > 0)
  )


def mean_rev_exit_mask(
  dataframe: "pd.DataFrame",
  *,
  sell_rsi: int = 50,
  bb_mid_tolerance: float = 0.005,
) -> "pd.Series":
  """Salida mean-rev: cierre en banda media o RSI de sobreventa recuperado."""
  return (
    (dataframe["close"] >= dataframe["bb_middle"] * (1 - bb_mid_tolerance))
    | (dataframe["rsi"] > sell_rsi)
  )


# Alias documentados en REGIME_SWITCHER.md (rama RANGE en 1h)
mean_rev_range_entry_mask = mean_rev_entry_mask
mean_rev_range_exit_mask = mean_rev_exit_mask


def resolve_regime_switcher_signal_exit(
  enter_tag: str | None,
  exit_cond_trend: bool,
  exit_cond_range: bool,
) -> str | None:
  """
  Dispatch puro enter_tag → tag de salida por señal.

  Solo consulta la columna de salida de la rama de entrada; ignora la condición contraria.
  """
  if enter_tag == TREND_ENTER_TAG:
    return TREND_SIGNAL_EXIT_TAG if exit_cond_trend else None
  if enter_tag == MEAN_REV_ENTER_TAG:
    return MEAN_REV_SIGNAL_EXIT_TAG if exit_cond_range else None
  return None


# --- GridDCA: presupuesto, capas y ajustes ---

DEFAULT_DCA_LAYER_FRACTIONS: tuple[float, ...] = (1.0, 0.5, 0.33, 0.25)
DEFAULT_DCA_MAX_ADDITIONAL_ENTRIES = 3
DEFAULT_DCA_MIN_DROP_PCT = 0.02
DEFAULT_DCA_ATR_DROP_MULTIPLIER = 1.5
DEFAULT_GRID_MAX_POSITION_RATIO = 0.15


def regime_allows_grid_dca(regime: MarketRegime | None) -> bool:
  """Solo añadir compras en régimen no-BEAR; BEAR congela ajustes."""
  return regime is not None and regime != MarketRegime.BEAR


def compute_dca_layer_stakes(
  max_position_budget: float,
  layer_fractions: tuple[float, ...] = DEFAULT_DCA_LAYER_FRACTIONS,
) -> list[float]:
  """Reparte presupuesto máximo en capas decrecientes (inicial + DCA)."""
  if max_position_budget <= 0 or not layer_fractions:
    return []
  total_frac = sum(layer_fractions)
  if total_frac <= 0:
    return []
  return [max_position_budget * (f / total_frac) for f in layer_fractions]


def compute_dca_drop_threshold_pct(
  atr: float,
  reference_rate: float,
  *,
  min_drop_pct: float = DEFAULT_DCA_MIN_DROP_PCT,
  atr_drop_multiplier: float = DEFAULT_DCA_ATR_DROP_MULTIPLIER,
) -> float:
  """Umbral de caída para DCA — causal si ATR proviene de column_value_at_time."""
  if reference_rate <= 0 or atr <= 0:
    return min_drop_pct
  atr_pct = (atr_drop_multiplier * atr) / reference_rate
  return max(min_drop_pct, atr_pct)


def price_drop_pct_from_reference(reference_rate: float, current_rate: float) -> float:
  """Caída relativa respecto al precio de referencia (última entrada)."""
  if reference_rate <= 0:
    return 0.0
  return max(0.0, (reference_rate - current_rate) / reference_rate)


def projected_exposure_within_budget(
  current_stake: float,
  additional_stake: float,
  max_position_budget: float,
) -> bool:
  return (current_stake + additional_stake) <= max_position_budget + 1e-9


def cap_dca_stake_to_budget(
  current_stake: float,
  requested_stake: float,
  max_position_budget: float,
) -> float:
  """Recorta el stake adicional para no superar el presupuesto (fills parciales)."""
  if requested_stake <= 0:
    return 0.0
  headroom = max(0.0, max_position_budget - current_stake)
  return min(requested_stake, headroom)


def evaluate_dca_adjustment(
  *,
  successful_entries: int,
  max_additional_entries: int,
  current_stake: float,
  next_layer_stake: float,
  max_position_budget: float,
  reference_entry_rate: float,
  current_rate: float,
  atr: float | None,
  regime: MarketRegime | None,
  min_drop_pct: float = DEFAULT_DCA_MIN_DROP_PCT,
  atr_drop_multiplier: float = DEFAULT_DCA_ATR_DROP_MULTIPLIER,
  min_stake: float | None = None,
) -> tuple[float | None, str]:
  """
  Decide si añadir una capa DCA y cuánto stake (recortado al presupuesto).

  successful_entries: nr_of_successful_entries de Freqtrade (incluye entrada inicial).
  """
  if not regime_allows_grid_dca(regime):
    return None, "regimen_BEAR_congela_dca"

  adjustments_done = max(0, successful_entries - 1)
  if adjustments_done >= max_additional_entries:
    return None, "max_ajustes_alcanzado"

  if next_layer_stake <= 0:
    return None, "capa_sin_stake"

  threshold = compute_dca_drop_threshold_pct(
    atr if atr is not None and atr > 0 else 0.0,
    reference_entry_rate,
    min_drop_pct=min_drop_pct,
    atr_drop_multiplier=atr_drop_multiplier,
  )
  drop = price_drop_pct_from_reference(reference_entry_rate, current_rate)
  if drop < threshold:
    return None, f"caida_insuficiente:{drop:.4f}<{threshold:.4f}"

  capped = cap_dca_stake_to_budget(current_stake, next_layer_stake, max_position_budget)
  if capped <= 0:
    return None, "presupuesto_agotado"

  if not projected_exposure_within_budget(current_stake, capped, max_position_budget):
    return None, "presupuesto_excedido"

  if min_stake is not None and capped < min_stake:
    return None, f"stake_bajo_minimo:{capped:.2f}<{min_stake:.2f}"

  return capped, "ok"


def get_trade_last_entry_rate(trade: object) -> float:
  """Precio de la última entrada (fill) — referencia DCA más precisa que open_rate medio."""
  orders = getattr(trade, "orders", None) or []
  prices: list[float] = []
  for order in orders:
    if isinstance(order, dict):
      is_entry = order.get("ft_is_entry") or order.get("is_entry")
      price = order.get("safe_price") or order.get("average") or order.get("price")
    else:
      is_entry = getattr(order, "ft_is_entry", False)
      price = getattr(order, "safe_price", None) or getattr(order, "average", None)
    if is_entry and price is not None:
      prices.append(float(price))
  if prices:
    return prices[-1]
  return float(getattr(trade, "open_rate", 0) or 0)


def count_trade_position_adjustments(trade: dict) -> int:
  """Cuenta compras adicionales (entradas tras la inicial) en export de backtest."""
  orders = trade.get("orders") or []
  entry_count = sum(1 for o in orders if o.get("ft_is_entry") or o.get("is_entry"))
  if entry_count > 0:
    return max(0, entry_count - 1)
  nr = trade.get("nr_of_successful_entries")
  if nr is not None:
    return max(0, int(nr) - 1)
  return 0


def trade_total_entry_stake(trade: dict) -> float:
  """Exposición total en entradas desde export de backtest."""
  orders = trade.get("orders") or []
  entries = [o for o in orders if o.get("ft_is_entry") or o.get("is_entry")]
  if entries:
    return sum(float(o.get("stake_amount") or o.get("cost") or 0) for o in entries)
  return float(trade.get("stake_amount") or trade.get("max_stake_amount") or 0)


def evaluate_correlation_entry(
  high_corr_count: int,
  max_correlated_open_positions: int,
  insufficient_pairs: list[str],
  *,
  insufficient_policy: str = "allow",
) -> tuple[bool, str]:
  """
  Política de correlación entre posiciones abiertas.

  - Si high_corr_count >= max_correlated_open_positions → rechazar
  - Si faltan datos históricos:
    - allow: permitir con log (default pragmático en backtest)
    - reject: no abrir por precaución
  """
  if high_corr_count >= max_correlated_open_positions:
    return False, f"correlacion_alta_con_{high_corr_count}_posiciones_abiertas"

  if insufficient_pairs and insufficient_policy == "reject":
    pairs = ",".join(insufficient_pairs[:3])
    return False, f"correlacion_historial_insuficiente:{pairs}"

  if insufficient_pairs and insufficient_policy == "allow":
    return True, f"correlacion_historial_insuficiente_allow:{len(insufficient_pairs)}"

  return True, "ok"
