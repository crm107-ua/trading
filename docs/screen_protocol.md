# Screen pre-validación — criterios congelados (no calibrar tras ver resultados).

## Objetivo

Cribado barato **antes** de `run_validation --profile full`. Un screen aprobado solo compra el derecho a gastar cómputo de validación; **no** implica robustez.

El screen **no** usa hyperopt — solo defaults y variantes manuales en JSON.

## Criterios de veredicto

### PASA a validación full

Al menos **una** variante cumple **las tres** condiciones sobre la ventana completa del backtest:

1. **PnL bruto > 0** (`profit_gross_abs > 0`)
2. **Comisiones < 50% del PnL bruto** de esa variante (`total_fees_abs < 0.5 * profit_gross_abs`)
3. **Nº trades ≥ 30**

### DESCARTADA

Ninguna variante logra PnL bruto > 0.

### ZONA GRIS

Alguna variante tiene PnL bruto > 0 pero **no** cumple fricción (< 50% comisiones) **o** trades (< 30). Requiere decisión humana documentada por escrito **antes** de lanzar validación full.

## Métricas parseadas

| Campo | Fuente |
|-------|--------|
| `profit_net_abs` | `profit_total_abs` del zip |
| `total_fees_abs` | suma de fees en trades del zip |
| `profit_gross_abs` | `profit_net_abs + total_fees_abs` |
| `trades` | recuento de trades |
| `sharpe` | informativo (no gate del screen) |
| `max_drawdown_account` | informativo |

## Artefactos

- `screen_report.json` en `user_data/validation_reports/screen/<Estrategia>/<run_id>/`
- Incluye variantes, métricas, veredicto y `reasons`

## Relación con validación full

- Screen aprobado → candidato a `python -m pipeline.run_validation <Estrategia> --profile full`
- Veredicto full (ROBUSTA/DUDOSA/SOBREAJUSTADA) es independiente del screen

## Aislamiento de estado (post-lock — ver `docs/validation_incidents.md`)

Mientras haya un `run_validation` activo, el screen **no** debe escribir en `user_data/backtest_results/` ni mutar `user_data/hyperopt_results/.last_result.json` compartidos con el pipeline.

Fix planificado en `screen_strategy.py`:

- Directorio de export dedicado por corrida de screen, o
- Snapshot/restore automático de `.last_result.json` alrededor de cada backtest.

Paralelismo seguro = aislamiento de estado, no disciplina manual.
