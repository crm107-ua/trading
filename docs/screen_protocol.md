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

### Sanity-check de fees (automático)

Si alguna variante tiene `trades > 100` y `total_fees_abs < trades × 10 USDT × 0.001`, el reporte se marca `invalid: fees_suspicious`, el veredicto queda anulado y `fee_sanity.warnings` documenta el motivo. Cubre regresiones del parseo ratio-vs-USDT (fallo-en-vacío #9).

## Artefactos

- `screen_report.json` en `user_data/validation_reports/screen/<Estrategia>/<run_id>/`
- Incluye variantes, métricas, veredicto y `reasons`

## Relación con validación full

- Screen aprobado → candidato a `python -m pipeline.run_validation <Estrategia> --profile full`
- Veredicto full (ROBUSTA/DUDOSA/SOBREAJUSTADA) es independiente del screen

## Rotación / cross-sectional (2026-07-10)

Aplica a estrategias de ranking multi-par (p. ej. **XSecMomentum**, intento **#10**).

### Criterios adicionales (PRE-REGISTRADOS)

Además de los tres criterios estándar del screen, **PASA** solo si **todas** se cumplen:

1. Criterios estándar: PnL bruto > 0, comisiones < 50% bruto, trades ≥ 30
2. **Leave-one-out bruto > 0**: re-backtest excluyendo el par de mayor contribución al PnL
3. **Max drawdown < 60%** (`max_drawdown_account < 0.60`)

El reporte debe citar el número de intento del registro de hipótesis.

### Ejecución

```powershell
python user_data/tools/screen_strategy.py XSecMomentum `
  --timerange 20210101- `
  --screen-config user_data/config/screen_xsec.json `
  --bias-controls --hypothesis-attempt 10
```

Modo `--bias-controls`: duplica backtests (baseline + leave-one-out por variante).

## Aislamiento de estado (post-lock — ver `docs/validation_incidents.md`)

Mientras haya un `run_validation` activo, el screen **no** debe escribir en `user_data/backtest_results/` ni mutar `user_data/hyperopt_results/.last_result.json` compartidos con el pipeline.

Fix planificado en `screen_strategy.py`:

- Directorio de export dedicado por corrida de screen, o
- Snapshot/restore automático de `.last_result.json` alrededor de cada backtest.

Paralelismo seguro = aislamiento de estado, no disciplina manual.
