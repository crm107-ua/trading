# Invalidación del screen #15 — runs no vinculantes

**Fecha cierre:** 2026-07-13  
**Veredicto vinculante único:** **SCREEN INVÁLIDO** — hipótesis **no evaluable** con los datos disponibles.  
**Artefacto final:** `research/output/poly_15/20260713_screen/report.json`

El pre-registro exigía **un solo run con veredicto vinculante**. Los intentos intermedios se invalidan aquí; **no** cuentan como muerte de mercado.

---

## Por qué no hay veredicto MUERTA

| Categoría | Qué mide | Aplica a #15 |
|-----------|----------|--------------|
| **MUERTA (D-*)** | La hipótesis falla bajo datos y sim honestos | **No** — no hubo screen informativo |
| **SCREEN INVÁLIDO** | El simulador o los datos no pueden juzgar la hipótesis | **Sí** |
| **NO EVALUABLE** | Faltan datos mínimos (depth WS ≥30 días) | **Sí** |

Una muerte por generador defectuoso es información sobre el **sim**, no sobre Polymarket.

---

## Runs invalidados (no vinculantes)

| Orden | Síntoma reportado | Bug / causa | Por qué invalida |
|-------|-------------------|-------------|------------------|
| 1 | MUERTA **(D-4)**, fill_rate ~4,6% | `order_count` incluía todos los ticks, no solo órdenes con edge | D-4 medía denominador incorrecto |
| 2 | MUERTA **(D-5)**, PnL ~−9 097 USDC | Múltiples fills por ventana; cada fill restaba bankroll, una sola resolución | Contabilidad de posiciones rota |
| 3 | MUERTA **(D-5)**, PnL ~−5 713 USDC | Fix parcial de posiciones; PnL aún no confiable | Misma clase de bug |
| 4 | MUERTA **(D-5)**, PnL ~−5 628 USDC | Generador v1: `resolved_up = int(rng.random() > 0.5)` **independiente** del path spot | **D-5 mide el generador**, no la hipótesis — estrategia fair-value no puede ganar resolución por construcción |
| 5 | (fix posterior) `resolved = int(window_end_spot > strike)` | Corrige coin-flip pero sigue siendo **synthetic mid+depth** sin calibrar | No sustituye depth WS real; pre-reg exige replay de sesiones grabadas |

Ninguna de estas filas debe permanecer como veredicto en `hypothesis_registry.md`.

---

## Datos mínimos no reunidos

Fase 0 (`POLYMARKET_FEASIBILITY.md`) ya fijó:

- `prices-history` = **mid-only**, sin depth histórico gratuito
- GO-live / screen honesto = **≥30 días** de depth WS propio (`clob_recorder`)
- Grabación realizada: muestras de segundos/minutos, no un panel evaluable

**Conclusión de mercado:** **ninguna** — #15 no alcanzó screen honesto. No afirmar ausencia de edge en Polymarket; solo que **no se pagó el coste de datos** para averiguarlo (prior 0/14 en Binance).

---

## Estado de la rama

| Componente | Estado |
|------------|--------|
| Hipótesis #15 | **Cerrada — no evaluable** |
| Rama `polymarket/` | **PAUSA** (código y docs se conservan) |
| Intento #16 | **No abierto** |
| Activos transferibles | Collectors, simulador, pre-reg, disciplina Fase 0 |

---

## Lección de diseño (sim)

El generador sintético debe cumplir **antes** de emitir veredicto:

1. Resolución **path-dependent**: `resolved_up = 1` iff `spot_final > strike` (regla del mercado real)
2. Stale quotes **no** decorrelacionados de la resolución
3. Prohibido emitir `MUERTA`/`PASA` desde `--synthetic` sin flag explícito de dev

Ver `sim_stale_quote.py`: `run_screen()` rechaza synthetic para veredicto vinculante.

---

*Un solo veredicto en registry. Runs intermedios solo en este archivo.*
