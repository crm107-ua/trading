# Operaciones y validación anti-lookahead

## Pipeline obligatorio antes de confiar en un backtest

Ejecutar en este orden (`scripts/backtest_all.ps1` / `.sh`):

| Paso | Herramienta | Qué valida | Bloqueante |
|------|-------------|------------|------------|
| 1 | `signal_truncation_check.py` | `enter_long` / `exit_long` idénticos al truncar datos futuros | **Sí** |
| 2 | `recursive-analysis` | Indicadores estables con distinto warmup | **Sí** |
| 3 | `lookahead-analysis` (trade-based) | Reproducibilidad de trades en backtest completo | **Advisory** |
| 4 | `backtesting` | Smoke de ejecución | Sí (sin errores) |

### 1. Test de señales truncadas (guard principal)

```powershell
docker compose run --rm --entrypoint python freqtrade user_data/tools/signal_truncation_check.py `
  --strategy MeanRevBB --timerange 20240101-20240320
```

Compara las columnas `enter_long` y `exit_long` entre el dataframe completo y versiones cortadas en N puntos posteriores al `startup_candle_count`. Las señales deben ser función pura del pasado: **cero diferencias** tras el warmup. No hay estado de "inconcluso".

### 2. Recursive-analysis

Valida que EMA200@4h, ATR, ADX, etc. convergen con el warmup configurado (`compute_startup_candle_count`: 850 en 1h, 3250 en 15m).

### 3. Lookahead trade-based (advisory)

El comando nativo `freqtrade lookahead-analysis` recorta el histórico y re-ejecuta **backtests completos**, comparando si los mismos trades se reproducen. Es útil en estrategias simples (p. ej. cruce EMA sin ROI table).

**No es bloqueante** en estrategias con:

- `minimal_roi` escalonada + `use_exit_signal`
- `custom_stoploss` / `custom_stake_amount` (ciclo de vida de trades)

#### Evidencia: dependencia de ruta (no fuga de indicadores)

Se reprodujo bias en un `IStrategy` puro (`PureSmokeStrategy`) con solo EMA 9/21:

- Con `minimal_roi` activa → `bias detected` en entradas
- Con `minimal_roi = {"0": 100}` → inconcluso por pocos trades, sin bias

El `recursive-analysis` seguía limpio. Conclusión: el test trade-based mezcla **dependencia de ruta del ciclo de trades** con detección de fuga real.

#### Callbacks y lookahead real en runtime

En backtest, los callbacks (`custom_stoploss`, `custom_stake_amount`, `confirm_trade_entry`) reciben el dataframe analizado **completo**. Leer `dataframe.iloc[-1]` usa el final del histórico, no `current_time` → lookahead real.

**Regla en `QuantBaseStrategy`:** usar `column_value_at_time()` (`quant_core.py`) con `timeframe_to_prev_date`, nunca `iloc[-1]` del histórico completo. Tests unitarios inyectan ATR absurdo en la cola y verifican que el stoploss en `current_time` intermedio no lo usa.

## Resultados de backtest pre-corrección (contaminados)

**No comparar métricas de backtests ejecutados antes de la corrección de callbacks causales** (commit con `_atr_at_time` / `column_value_at_time`).

Hasta esa corrección, `custom_stoploss` y `custom_stake_amount` leían ATR y régimen con `dataframe.iloc[-1]` — el final del histórico en backtest, no `current_time`. Eso inflaba o deflaccionaba stops y sizing de forma no reproducible en live.

Los smoke-tests de Fase 1–3 anteriores a ese fix **no son baseline válidos**. Solo los backtests posteriores al fix + pipeline `signal_truncation` + `recursive-analysis` son comparables.

## Criterio de desbloqueo (nuevas estrategias / BreakoutVol)

1. `signal_truncation_check.py` en verde para la estrategia
2. `recursive-analysis` sin bias en indicadores
3. Callbacks auditados (sin `iloc[-1]` en lecturas de dataframe analizado)
4. Confirmación con datos reales al descargar histórico (verificación adicional, no árbitro)

## Datos reales

Tras `scripts/download_data.ps1`, repetir el pipeline sobre timerange largo. Los datos reales pueden cambiar la frecuencia de trades pero **no sustituyen** el test de señales truncadas.

## BreakoutVol — notas de construcción

Errores dentro de la vela (no detectados por signal-truncation) que la estrategia evita explícitamente:

| Tema | Implementación |
|------|----------------|
| Máximo rolling | `high.rolling(N).max().shift(1)` vía `compute_prior_rolling_max` — la vela actual no cuenta en su umbral |
| Volumen confirmación | `volume.rolling(N).mean().shift(1)` — compara contra media **previa**, sin incluir volumen actual |
| Entrada | Señal al cierre de ruptura; ejecución en apertura siguiente (modelo pesimista, sin `custom_entry_price`) |
| Salida invalidación | `close < range_high`; `use_exit_signal=True` → lookahead trade-based advisory esperado |

## Docker: contenedor `unhealthy` durante hyperopt

`docker compose run` para hyperopt/backtest **no** arranca el servicio `freqtrade` con api_server. El healthcheck del compose (`curl …/api/v1/ping`) solo aplica al servicio `trade` de larga duración.

Los contenedos efímeros de `docker compose run … hyperopt` pueden aparecer como **unhealthy** en `docker ps` si heredan o exponen healthcheck sin api_server — es **benigno** durante batches de hyperopt de horas/días. No interpretar `unhealthy` como fallo del run salvo que el proceso haya salido o los logs muestren error.

Los números de backtest sobre **fixtures** (p. ej. TrendRider +64 % en `20240101-20240320`) están diseñados para *disparar* señales en ventanas sintéticas; **no citar como estimación de rentabilidad**.

---

## Dry-run XSecMomentum-m35 (Fase 5)

Aislamiento completo del pipeline MeanRevBB. Ver `docs/dryrun_protocol.md`.

| Recurso | Valor |
|---------|-------|
| Compose | `docker-compose.dryrun.yml` (no tocar `docker-compose.yml`) |
| Contenedor | `xsec-dryrun` |
| API | http://127.0.0.1:8082 |
| DB | `user_data/dryrun_xsec.sqlite` |
| Params | `user_data/strategies/XSecMomentum_m35_frozen.json` |
| Reloj inicio | `user_data/dryrun_xsec_started.json` |

### Arrancar

```powershell
.\scripts\start_xsec_dryrun.ps1
```

### Monitor (cada 5 min)

**Produccion:** tarea programada Windows (sobrevive reinicios; reinicia si el proceso muere):

```powershell
.\scripts\install_monitor_task.ps1   # una vez: registra + arranca Trading-XSec-Dryrun-Monitor
Get-ScheduledTask -TaskName Trading-XSec-Dryrun-Monitor | Get-ScheduledTaskInfo
```

Log de la tarea: `user_data/logs/dryrun_monitor_task.log`

**Manual / depuracion:**

```powershell
python -m risk.monitor          # bucle (muere con la sesion)
python -m risk.monitor --once   # un ciclo
```

Estado: `user_data/dryrun_monitor_state.json` · bandera alerta: `user_data/dryrun_monitor_alert.flag`

El reporte semanal incluye **edad del ultimo heartbeat**; si lleva >= 3 dias sin actualizar, el monitor esta mudo.

### Primer rebalanceo en vivo

Senal al **cierre del lunes** (vela 1d); ejecucion esperada **martes al open**. Primer evento: **lun 13 / mar 14 jul 2026**. FreqUI dry-run: http://127.0.0.1:8082 — el monitor alerta si la entrada cae fuera de lun/mar.

### Parar

```powershell
docker compose -f docker-compose.dryrun.yml down
```

### Reporte semanal (manual)

```powershell
python scripts/weekly_report.py
```

Salida: `user_data/reports/weekly/<ISO-week>.md`

### Alertas

| Código | Condición |
|--------|-----------|
| `bot_down` | API no responde |
| `drawdown_high` | DD dry-run > 15% |
| `stale_position` | Posición abierta > 21 días |
| `rebalance_timing_violation` | Entrada fuera de lun/mar |

### Go-live (bloquea hasta verde)

```powershell
python scripts/go_live_check.py --strategy XSecMomentum
```

Hoy debe fallar todo (sin veredicto ROBUSTA, brecha sin datos).

### Brecha (futuro, post-veredicto)

```powershell
python user_data/tools/dryrun_gap_report.py --db user_data/dryrun_xsec.sqlite `
  --backtest-zip <zip> --timerange <igual-al-dryrun> --output user_data/dryrun_gap_report.json
```
