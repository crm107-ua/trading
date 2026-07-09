# RegimeSwitcher — decisiones de diseño (Fase 3)

Documento de referencia **antes de implementar**. Evita improvisación en composición, timeframes, salidas y hyperopt.

## 1. Composición por funciones puras (no herencia múltiple)

**No** instanciar `TrendRider` / `MeanRevBB` dentro del switcher ni heredar de ambas.

Patrón acordado con la arquitectura actual:

1. Extraer condiciones de entrada/salida a funciones puras en `quant_core.py` (máscaras booleanas sobre `DataFrame`).
2. `RegimeSwitcher` (timeframe 1h) elige qué función aplicar según `btc_market_regime` por vela.
3. Una sola clase hereda `QuantBaseStrategy` → un solo conjunto de protecciones, callbacks y `startup_candle_count`.

Ejemplo de API objetivo:

```python
# quant_core.py
def trend_rider_entry_mask(df, params) -> pd.Series: ...
def trend_rider_exit_mask(df, params) -> pd.Series: ...
def mean_rev_range_entry_mask(df, params) -> pd.Series: ...  # 1h, no MeanRevBB 15m
def mean_rev_range_exit_mask(df, params) -> pd.Series: ...
```

`RegimeSwitcher.populate_entry_trend` delega en la máscara del régimen activo y asigna `enter_tag` (`trend` / `mean_rev`).

## 2. Conflicto de timeframes — decisión explícita

| Estrategia fuente | Timeframe | RegimeSwitcher |
|-------------------|-----------|----------------|
| TrendRider | 1h | 1h (misma lógica, params transferibles) |
| MeanRevBB | 15m | **1h** (lógica mean-rev reimplementada en 1h) |

**RegimeSwitcher-RANGE ≠ MeanRevBB.** Los rangos de hyperopt de MeanRevBB (15m) no se copian; los parámetros RANGE del switcher se optimizan por separado en 1h.

Documentar en docstring de la estrategia y en backtests de validación.

## 3. Salidas por `enter_tag` — restricción de mecanismo Freqtrade

### Lo que **no** funciona

**`populate_exit_trend` no puede ramificar por trade.** Es vectorizado por par: calcula columnas de salida sobre el dataframe sin saber qué trade está abierto ni con qué tag entró. Si allí se genera una señal de salida de lógica RANGE, cerrará también un trade abierto con tag `trend` en ese par.

`populate_exit_trend` debe quedar **vacío** o reservado solo para salidas universales (válidas para cualquier tag).

**Nota Freqtrade:** `custom_exit` solo se invoca si `use_exit_signal=True`. Con `populate_exit_trend` vacío no hay señales vectorizadas cruzadas; el flag solo habilita el callback por trade.

### Patrón correcto (encaja con `quant_core.py`)

1. **`populate_indicators`**: precomputar ambas condiciones como columnas causales:
   - `exit_cond_trend`
   - `exit_cond_range`
   (funciones puras en `quant_core.py` → testeables sin motor Freqtrade)

2. **`custom_exit(trade, ...)`**: único callback de salida que recibe el `Trade` y su `enter_tag`. Dispatch trivial:
   - `enter_tag == "trend"` → consultar `exit_cond_trend` vía `column_value_at_time` en `current_time`
   - `enter_tag == "mean_rev"` → consultar `exit_cond_range` vía `column_value_at_time`
   - Mismo patrón causal que `custom_stoploss` / `_atr_at_time` (nunca `iloc[-1]`)

3. **`custom_stoploss`**: trailing ATR compartido; no mezclar reglas de salida por régimen aquí.

| `enter_tag` | Entrada | Salida |
|-------------|---------|--------|
| `trend` | `trend_rider_entry_mask` | `exit_cond_trend` en `custom_exit` + trailing ATR |
| `mean_rev` | `mean_rev_range_entry_mask` | `exit_cond_range` en `custom_exit` |

**No** usar `btc_market_regime` actual para decidir la salida de un trade abierto — el régimen puede haber cambiado desde la entrada.

## 4. Hyperopt por ramas

El switcher hereda parámetros de dos lógicas; exponer todos superará el límite práctico de 6–8 parámetros optimizables.

**Decisión recomendada (elegir una y documentarla en la estrategia):**

- **Opción A — Congelar régimen, optimizar ramas:** parámetros de régimen (EMA200/ADX) compartidos con la base, **no** en hyperopt del switcher. Exponer solo 3–4 parámetros por rama (`trend_*`, `range_*`).
- **Opción B — Trasplante:** optimizar TrendRider y la rama RANGE del switcher por separado en backtests 1h; fijar valores en `RegimeSwitcher` sin hyperopt conjunto.

Cualquiera vale; debe ser **deliberado**, no acumulación accidental de `IntParameter` de ambas madres.

## 5. Test de integración crítico (post-implementación)

Sobre fixture BULL+RANGE (`backtest_fixtures.json`), el test que verifica la trampa de salidas:

1. Backtest con trades exportados (`export: trades`).
2. Afirmar que existen trades con **ambos** `enter_tag` (`trend` y `mean_rev`).
3. Afirmar que **ningún** trade con `enter_tag=trend` se cierra por señal `mean_rev_signal` (y recíproco), filtrando solo `exit_reason` de señal custom (`trend_signal` / `mean_rev_signal`). Stoploss ATR y protecciones no se auditan.
4. **Dispatch ejercitado:** test unitario `resolve_regime_switcher_signal_exit` + integración con `RegimeSwitcherWideStop` (stop -99%, sin protecciones) y `--min-signal-exits 1` en ventana RANGE de fixtures.

Ver `tests/test_smoke_backtest.py::test_regime_switcher_exit_respects_enter_tag` (activo cuando exista la estrategia).

## 6. Nota anticipada — GridDCA

`adjust_trade_position()` recibe el dataframe analizado completo en backtest — mismo antipatrón que `custom_stoploss` antes del fix.

**Obligatorio:** cualquier lectura de indicadores en DCA usa `column_value_at_time()` con `current_time`, nunca `iloc[-1]` del histórico completo.

Ver `docs/OPERATIONS.md` (callbacks causales).

## Validación previa a merge

### CI (fixtures — `tests/fixtures/data`)

- `regime_variety_check.py` en verde
- `signal_truncation_check.py` en verde
- `recursive-analysis` limpio
- Trades > 0 BULL/RANGE (`tests/test_smoke_backtest.py`)

### Datos reales (`user_data/data`)

- `backtest_all.ps1 -RealData` × TrendRider, MeanRevBB, BreakoutVol
- Comparar recuentos de trades vs fixtures; divergencias esperables, pero MeanRevBB con filtro RANGE real debe diferir del comportamiento pre-fix (operaba sin filtro efectivo)
