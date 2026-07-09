# GridDCA — diseño y validación

Estrategia 1h spot con hasta **3 compras adicionales** decrecientes vía `adjust_trade_position()`.

## Riesgos (documentar antes de operar)

Promediar a la baja en tendencia bajista puede ser ruinoso. La entrada solo ocurre en régimen **no-BEAR**, pero la pregunta peligrosa es si se **siguen añadiendo** compras cuando BTC ya cruzó a BEAR.

**Decisión:** en BEAR se **congelan** los ajustes (`regimen_BEAR_congela_dca`). La posición promediada queda gobernada solo por el stop global ATR sobre `trade.open_rate` (promedio actualizado por Freqtrade tras cada fill).

## Presupuesto (invariante)

- `grid_max_position_ratio` (default 15% del wallet) define el tope por posición.
- Capas `1.0 : 0.5 : 0.33 : 0.25` reparten ese presupuesto.
- `evaluate_dca_adjustment` + `cap_dca_stake_to_budget` garantizan que ningún fill parcial supera el tope.
- Tests: unitarios + property-based (`hypothesis`) sobre secuencias de fills.

## Causalidad

Toda lectura de indicadores en `adjust_trade_position` usa `column_value_at_time()` — nunca `iloc[-1]`. Test replicado: ATR=999 en cola no afecta umbral de caída en `current_time` intermedio.

## Stop global

`custom_stoploss` delega en la base usando `trade.open_rate` — Freqtrade recalcula el promedio tras cada DCA; no cachear el precio de entrada original.

## Tests de integración

| Herramienta | Flag | Qué verifica |
|-------------|------|--------------|
| `grid_dca_check.py` | `--min-position-adjustments 3` | Al menos un trade con 3 compras adicionales |
| `grid_dca_check.py` | `--require-stop-after-dca` | Ciclo DCA→stop (no vacío) |
| Fixture | `inject_grid_dca_drawdown` | Caída escalonada 5%/vela × 8 en ventana BULL |

## Datadir en CI

Freqtrade **ignora** `"datadir"` en `backtest_fixtures.json` si no se pasa `--datadir` por CLI: `create_datadir()` cae en `user_data/data` por defecto. Los tools programáticos usan `fixture_config.load_fixture_backtest_config()`; Docker backtest usa `--datadir /freqtrade/user_data/fixtures/data/binance`.

En backtest, `current_entry_rate` coincide con el open de la vela actual — la referencia DCA es `get_trade_last_entry_rate(trade)`, no `current_entry_rate`.

Regenerar fixtures tras cambios: `scripts/regenerate_fixtures.ps1`

| `grid_dca_breakdown.py` | `--zip` o `--real-data` | Distribución 0/1/2/3 ajustes, exit_reason, force_exit |

## Backtest real pre-hyperopt (20230101-20240320)

Sobre 1757 trades con defaults:

| Ajustes | Trades | % | PnL neto medio |
|---------|--------|---|----------------|
| 0 | 1746 | 99.4% | -2.04 USDT |
| 1 | 11 | 0.6% | -16.02 USDT |
| 2–3 | 0 | 0% | — |

- **Ningún trade completó el grid de 3 capas** en datos reales con defaults.
- `force_exit`: solo 3 trades (0.2%), todos al cierre del timerange — no explican el -37%.
- **El PnL negativo es casi enteramente comportamiento de la entrada base**, no del DCA. La hipótesis grid no se está probando en este histórico con `dca_min_drop_pct=2%` y caídas escalonadas del 5% (raras fuera de crashes).

El mecanismo DCA sí se ejercita en fixtures (`grid_dca_check`); en real hay que bajar umbral de caída o ampliar ventana para ver si el grid aporta edge — eso es trabajo de Fase 4, no de rescatar defaults.

## Hyperopt (Fase 4)

Como el resto de estrategias: defaults sin optimizar. PnL bruto negativo pre-hyperopt no invalida el mecanismo; el veredicto del pipeline decide si hay edge.
