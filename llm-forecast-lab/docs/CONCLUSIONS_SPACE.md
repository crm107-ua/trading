# Espacio de conclusiones (pre-resultados)

**Fecha:** 2026-07-15  
**Estado:** cerrado por adelantado — antes de ver el veredicto v1  
**Protocolo:** `config/eval_frozen.json`, `docs/PROTOCOL.md`

Este documento es la tercera pieza del ritual del día D:

1. Expectativas pre-registradas (`PROTOCOL.md`, hipótesis en registry)
2. Compromiso de lectura en frío: **`report.json` → `integrity` primero** (tripwires), luego `verdict`, luego skill — ver PROTOCOL § Semántica de lectura
3. **Este archivo** — espacio de conclusiones cerrado *antes* de conocer el resultado

El día D no habrá nada que interpretar: solo localizar el veredicto en una tabla escrita cuando aún no se conocía la respuesta. Es la versión eval de las muertes pre-escritas, aplicada también a la victoria.

---

## Qué entrega el pipeline

Al completar ingest → gate (`ingest-cascade`) → forecast → score → report, las conclusiones salen de `report.json` y están acotadas por el protocolo congelado.

---

## 1. Veredicto principal (una de cuatro)

| Veredicto | Significado |
|-----------|-------------|
| **`BELOW_MARKET`** | NVIDIA NIM `meta/llama-3.3-70b-instruct` predice peor que el mid de mercado en held-out |
| **`MATCHES_MARKET`** | Skill ≈ 0 (±5%) y el IC bootstrap cruza cero — empata con el mercado |
| **`BEATS_MARKET`** | Skill > 0 con IC95 > 0 — bate al mercado de forma estadísticamente defendible |
| **`EVAL_INVALID`** | No se puede publicar veredicto de skill (held-out < 100, fallos de forecast, contaminación dura en muestra eval, etc.) — **no** incluye tripwires de canario/temporal (`auditRequired`) |

**Expectativa pre-registrada:** `BELOW_MARKET` o `MATCHES_MARKET`. Si sale `BEATS_MARKET`, la primera sospecha es bug o leakage, no genialidad del modelo.

---

## 2. Conclusiones cuantitativas concretas

Sobre **~150 preguntas held-out** (último 30% temporal de 500 muestreadas):

- **¿El LLM calibra bien?** — Brier, log loss, bins de calibración + ECE vs mercado
- **¿Cuánto mejor/peor?** — Skill = `1 − Brier_LLM / Brier_mercado` + bootstrap CI de la diferencia
- **¿Depende del horizonte?** — `brierByHorizon` en T−24h, T−72h, T−7d (esperado: peor cerca de resolución, donde el mercado lleva más señal)
- **¿El universo de la muestra es representativo?** — `selection.composition` (deportes, concentración en 2025, etc.)

---

## 3. Conclusiones de integridad (sí/no)

- **Leakage** — canarios con lag largo; si Brier sospechosamente bajo → `leakage_suspected`
- **Muestra válida** — `heldoutQuestionsN ≥ 100`, `forecastFailedRate ≤ 10%`
- **Universo keyset completo** — *gate pendiente:* `gamma_keyset_complete=true`, sin truncación documentada en rango 2024–2026; hasta entonces no afirmar universo completo en presente
- **Un solo modelo** — sin mezcla de proveedores (`mixed_models`); solo NVIDIA NIM en `models.json`

---

## 4. Qué SÍ podrás concluir (v1)

1. **En mercados Polymarket binarios resueltos, líquidos, ≥7 días**, un forecaster **NVIDIA NIM** (`meta/llama-3.3-70b-instruct`, cutoff 2023-12-01) **no supera** (o apenas empata con) el precio de mercado **como predictor probabilístico** en este universo — o hay evidencia fuerte de lo contrario.
2. **El mercado agrega información** que el LLM sin retrieval no replica (si `BELOW_MARKET`).
3. **Dónde falla** — por horizonte y por calibración (sobreconfianza/subconfianza).
4. **Si vale la pena seguir** con pipelines más ricos (decomposed, ensemble, retrieval) — solo como siguiente hipótesis pre-registrada, no como edge tradeable.

---

## 5. Qué NO podrás concluir

Esta sección es tan importante como la 4. Saber enumerar lo que un resultado *no* permite concluir separa un eval serio de un benchmark de marketing.

- **No hay PnL ni edge tradeable** — el eval mide precisión probabilística, no rentabilidad tras fees/slippage. No usar vocabulario de *alpha* ni de trading para formular el veredicto vinculante.
- **No generaliza a todo Polymarket** — solo al universo filtrado + muestra estratificada (probablemente muy 2025, con peso deportivo).
- **No invalida ni valida #16 maker** ni abre trading automático — es input para decidir si merece un intento posterior con fricción real.
- **Un solo modelo, un solo prompt** — no compara arquitecturas ni coste/beneficio API.

---

## 6. Escenarios al terminar

### Caso A — veredicto válido (`BELOW_MARKET` / `MATCHES_MARKET`)

Conclusión vinculante para v1:

> El forecaster NVIDIA NIM (`meta/llama-3.3-70b-instruct`) **no supera al precio de mercado como predictor probabilístico** en este universo (o empata dentro del umbral congelado).

Cierra la línea naive para v1; el siguiente paso sería otra hipótesis pre-registrada, no optimizar este prompt.

### Caso B — `BEATS_MARKET`

Auditar leakage e integridad antes de creerlo; no implementar nada hasta reproducir. La formulación vinculante, si sobrevive auditoría, sigue siendo predictiva — no tradeable.

### Caso C — `EVAL_INVALID`

Solo conclusión operativa: *el run no cumple protocolo*. Re-ejecutar; no interpretar skill ni skill score del reporte parcial.

---

## Una frase (sin overclaim)

Al terminar sabrás si un forecaster **meta/llama-3.3-70b-instruct** vía NVIDIA NIM **bate, empata o pierde contra el mercado** en predicción probabilística out-of-sample sobre el universo definido — con límites claros de muestra y composición, y sin claim de dinero.

Eso alimenta la decisión de seguir invirtiendo en forecasting LLM vs volver a maker/trading con otra hipótesis.

---

## Checklist operativo (no migrar al write-up en presente hasta verde)

- [ ] `gamma_keyset_complete=true`
- [ ] `dedupSanity` OK sobre total final
- [ ] `composition` / `verdictScopeNote` regenerados
- [ ] `run_questions`=500 regeneradas
- [ ] CLOB fase 2 sobre muestra
- [ ] `forecast --mode live` (con purga) → `score` → `report`
- [ ] `heldoutQuestionsN` ≥ 100
- [ ] Localizar veredicto en las tablas de este documento
