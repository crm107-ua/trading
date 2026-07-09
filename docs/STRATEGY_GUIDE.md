# Guía de estrategias — Fase 2

## Heredar de QuantBaseStrategy

Todas las estrategias del laboratorio deben heredar de `QuantBaseStrategy` (`user_data/strategies/_base.py`):

```python
from _base import QuantBaseStrategy

class MiEstrategia(QuantBaseStrategy):
    timeframe = "1h"

    def populate_indicators(self, dataframe, metadata):
        dataframe = super().populate_indicators(dataframe, metadata)
        # tus indicadores...
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        # señales de entrada...
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        # señales de salida...
        return dataframe
```

## Qué aporta la clase base

| Funcionalidad | Descripción |
|---------------|-------------|
| `informative_pairs()` | BTC/USDT en 4h para filtro de régimen |
| `market_regime()` | Etiqueta BULL / BEAR / RANGE (EMA200 + ADX) |
| `custom_stoploss()` | 2×ATR inicial → breakeven +2% → trailing 1×ATR +4% |
| `custom_stake_amount()` | Riesgo ~1% del capital por trade |
| `confirm_trade_entry()` | Bloquea spread >0.3%, régimen adverso, eventos vol |
| `protections` | StoplossGuard, MaxDrawdown, Cooldown, LowProfitPairs |

### Filtro de correlación (MeanRevBB y estrategias mean-rev)

Activar `correlation_filter_enabled = True`. No abre si ya hay
`max_correlated_open_positions` (default 2) posiciones abiertas con correlación de
retornos diarios (30d) > `correlation_threshold` (0.8) respecto al par candidato.

Datos: usa `dp.get_pair_dataframe()` del pairlist cargado (mismo timeframe de la estrategia).

| `correlation_insufficient_policy` | Comportamiento |
|-----------------------------------|----------------|
| `allow` (default) | Permite entrada; loguea `correlacion_historial_insuficiente_allow` |
| `reject` | Bloquea entrada; loguea `correlacion_historial_insuficiente` |

### Spread: backtest vs dry-run/live

El chequeo de spread usa `self.dp.runmode` — solo activo en `DRY_RUN` y `LIVE` (hay orderbook).
En `BACKTEST` y `HYPEROPT` se desactiva automáticamente para evitar discrepancias con el comparador de Fase 5.

### Stake mínimo del exchange

Política por defecto: `min_stake_policy = "reject"`. Si el stake por riesgo 1% queda por debajo
del `min_stake` del par, la entrada se **rechaza** y se loguea `stake_bajo_minimo`. Alternativa:
`min_stake_policy = "bump_to_min"` (acepta riesgo > 1%, loguea `stake_elevado_al_minimo`).

## Parámetros configurables por estrategia

```python
regime_filter_enabled = True   # filtro BTC
spread_check_enabled = True  # requiere orderbook (live/dry-run)
block_bear_longs = True        # no longs en BEAR
risk_per_trade = 0.01          # 1%
atr_stop_multiplier = 2.0
high_volatility_event = False  # placeholder noticias
```

## Lógica pura testeable

Las funciones en `quant_core.py` son importables en tests sin Docker:

- `compute_market_regime()`
- `compute_atr_stoploss_ratio()`
- `compute_risk_stake_amount()`
- `evaluate_entry_confirmation()`

## Datos requeridos

Para el filtro de régimen, descarga BTC/USDT en 4h (incluido en `download_data`):

```bash
./scripts/download_data.sh
```

## Siguiente fase

Fase 3: las cinco estrategias implementadas (TrendRider, MeanRevBB, BreakoutVol, RegimeSwitcher, GridDCA). Ver `docs/GRID_DCA.md`.

### MeanRevBB — política de hyperopt (Fase 4)

Backtest real pre-hyperopt: PnL **bruto negativo** (~-3.7k USDT) antes de comisiones (~4.4k). No hay edge que las fees erosionen; la hipótesis en 15m/spot con esta construcción es probablemente falsa. En Fase 4 tratarla como **caso de control de calibración**: lanzar `full`, mirar qué veredicto producen los umbrales por métricas puras; si sale ROBUSTA, endurecer umbrales y re-evaluar **antes** de leer las demás estrategias. No hay excepción hardcodeada en el motor — no intentar rescatarla a base de epochs (camino directo al overfitting). La rama `mean_rev` de RegimeSwitcher en 1h es otra construcción (menos trades, menos fricción relativa).

### Verificación lookahead (sin fuga temporal en informative BTC)

```bash
./scripts/lookahead_check.sh SmokeTestStrategy
# Windows:
pwsh scripts/lookahead_check.ps1 TrendRider
```

Debe completar sin indicadores marcados con lookahead bias.
