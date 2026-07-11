# Protocolo dry-run — XSecMomentum-m35

**Pre-registrado:** 2026-07-11, **antes** del primer arranque. El reloj de brecha empieza al levantar el contenedor; los datos solo se **leen** tras el veredicto de validación full.

---

## Config congelada

| Campo | Valor |
|-------|-------|
| Estrategia | `XSecMomentum` |
| Parámetros | `momentum_window=14`, `top_n=3`, `exit_rank_k=4`, `stoploss=-0.35` |
| Universo | E2 (16 pares USDT, `screen_xsec.json`) |
| Modo | `dry_run: true`, `dry_run_wallet: 10000` |
| Contenedor | `xsec-dryrun` (`docker-compose.dryrun.yml`) |
| API | puerto **8082** (aislado del lab 8080) |
| DB | `user_data/dryrun_xsec.sqlite` (propia) |

Params congelados en `user_data/strategies/XSecMomentum_m35_frozen.json` (copiados al arranque del contenedor).

---

## Advertencia — parámetros post-validación

La validación full puede producir parámetros hyperopt **distintos** a los del pre-registro.

Este dry-run mide **mecánica de ejecución** en primer orden:

- Fills y slippage vs backtest
- Timing de rebalanceo (señal lunes → ejecución martes open)
- Comportamiento del stop −35% en vivo simulado

Si los parámetros validados difieren, se documentará entonces si:

- se **reinicia** el reloj de brecha, o
- se **acepta** la medición mecánica como válida para go-live.

**Los datos del dry-run NO se miran para ajustar la validación.** Solo el comparador de brecha los lee, y solo **tras** el veredicto full.

---

## Duración mínima

Antes de cualquier decisión de go-live:

1. **≥ 4 semanas** de calendario desde `started_at`, y
2. **≥ 4 rebalanceos** ejecutados (estrategia semanal → pocos eventos; motivo de arrancar ya).

---

## Criterios de brecha (pre-fijados — lectura futura)

Cuando se invoque `user_data/tools/dryrun_gap_report.py` tras el veredicto:

| Criterio | Umbral |
|----------|--------|
| Slippage medio real | Documentar vs asumido (fee 0.1% / order book top) |
| Rebalanceos en timing esperado | Señal lunes / fill martes open |
| Divergencia PnL relativo vs backtest mismo timerange | **< 30%** |

---

## Aislamiento del pipeline

El dry-run **no** debe escribir en:

- `user_data/validation_reports/`
- `user_data/hyperopt_results/` (incl. `.last_result.json`)
- Contenedor `freqtrade-quant-lab` ni puerto 8080

Verificación: `docker-compose.dryrun.yml` sin montaje de `pipeline/`; DB y API propias.

---

## Riesgo abierto (13-E) — lectura del veredicto full

> El múltiplo absoluto Freqtrade contiene un factor **~3.6×** no reconciliado con el instrumento (13-E). El veredicto full debe apoyarse en **métricas relativas y de estabilidad** (WFE, % ventanas positivas, DD, LOO), **no** en el múltiplo.

Ver también `docs/XSEC_MOMENTUM.md` pre-registro validación.
