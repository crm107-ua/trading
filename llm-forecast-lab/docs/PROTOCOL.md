# PROTOCOL (frozen)

Este documento describe el protocolo que el sistema aplica leyendo `config/eval_frozen.json`.

## Qué se evalúa

- Preguntas binarias **resueltas** (v1: Polymarket fixtures; live ingestion vía Gamma keyset).
- Baseline: **market mid-price** en el timestamp del snapshot (horizontes fijos).

## Métricas (sin PnL)

- Brier score y log loss
- Calibración: bins + ECE
- Skill score: \(1 - \frac{\text{Brier}_{pipeline}}{\text{Brier}_{market}}\)
- Bootstrap CI sobre diferencia de Brier vs market

## Congelación

El runtime **rehúsa ejecutar** si el `freezeHash` de `eval_frozen.json` no coincide con el hash calculado.

## Universo de ingest (2026-07-13)

**Decisión congelada: opción (a) — keyset completo.**

- Ingest live usa `GET /markets/keyset` con `closed=true`, `order=end_date`, `ascending=true`, rango `resolutionFrom`–`resolutionTo`.
- Dedupe por `slug`; payload crudo cacheado en SQLite (`gamma_markets_raw`).
- Backoff conservador (500 ms/página; 60 s tras 429/403) para evitar Cloudflare 1015.
- **No** se usa el cap offset=2100 como universo evaluable; ese límite es solo para viability rápida.

## Muestreo de run (2026-07-13)

Antes de forecast/score/report en live:

1. **Universo post-filtros** — liquidez, binario Yes/No, outcome resuelto, disputa, rango de fechas (filtros congelados en cliente).
2. **Intersección de modelos** — solo preguntas elegibles para *todos* los modelos en `models.json` (cutoffs distintos).
3. **Muestreo estratificado** — seed fija (`runSampling.seed`), proporcional por trimestre de resolución y categoría (bucket `OTHER` si falta).
4. **Split temporal después** — held-out = último 30% por `resolution_date` sobre la muestra; mínimo 100 preguntas held-out (`minHeldoutQuestionsAfterSplit`).

Tamaño congelado: **500 preguntas** (→ ~150 held-out con margen sobre el umbral de 100).

Precios CLOB (`prices-history`) solo para la muestra seleccionada; cache en `data/clob/{token_id}.json`.

## Ajustes post-viabilidad / pre-resultados (2026-07-13)

- **Canarios con buffer**: ventana \([cutoff-maxLag, cutoff-minLag]\).
- **Potencia por pregunta**: bootstrap clusterizado por pregunta, no por horizonte.
- **Ensemble deshabilitado en v1** (`ensemble.enabled=false`); re-freeze antes de cualquier run ensemble.
- **Pipeline decomposed**: placeholder — no incluir en planes de run hasta implementación.
- **Duración mínima del mercado (2026-07-13, pre-ingest live):** `minMarketDurationDays: 7` — excluye ventanas efímeras (BTC 5m, hourly) que pasarían filtros binario/liquidez pero degeneran el eval en ruido ~0.50.
- **Keyset incremental (2026-07-13):** cada página persiste en `gamma_markets_raw` + cursor en `meta`; reanudación real tras 429 o crash.
- **v1 un solo modelo:** `meta/llama-3.3-70b-instruct` vía NVIDIA NIM (`NVIDIA_API_KEY` en `.env`, API gratuita). Sin fallback entre modelos; 429 → retry mismo modelo → `forecast_failed`. Guard `mixed_models` en report.
- **Cutoff documentado:** `trainingCutoff: 2023-12-01` — pretraining knowledge cutoff diciembre 2023 ([Meta Llama 3.3 model card](https://github.com/meta-llama/llama-models/blob/main/models/llama3_3/MODEL_CARD.md); verificado en [NVIDIA NIM catalog](https://docs.api.nvidia.com/nim/reference/meta-llama-3_3-70b-instruct)).
- **Re-freeze 2026-07-15 (mediodía):** N canarios 25; tripwires de auditoría separados de `EVAL_INVALID` duro.
- **Pipeline:** `naive` (prompt en `src/pipeline/forecasters/prompts/naive.txt`). **Provider:** NVIDIA (`--provider nvidia`). **Model:** `meta/llama-3.3-70b-instruct`. No confundir pipeline (estrategia de prompt) con provider.
- **Forecast batch:** ~1.500 llamadas; ~20 s/llamada en 70B → **8–12 h** en serie (+ rate limits). Run desatendido nocturno. **Resume por defecto** (sin purga): filas en `forecasts` + cache `data/responses/`; relanzar salta existentes. Purga solo con `--fresh`.

## Ajustes post-primeros-resultados (2026-07-15, tras abort de run)

### Fix de parsing — fences markdown (2026-07-15)

- **Qué pasó:** el primer run live devolvió `forecast_failed` al 100% con exit 0 silencioso (`forecasts: 0` en DB tras join sin snapshots; luego, con snapshots, fallo de `JSON.parse` porque `meta/llama-3.3-70b-instruct` envolvía el JSON en fences markdown `` ``` ``).
- **Fix:** `parseForecastOutput()` en `src/pipeline/schema.ts` — extrae JSON de fences o del primer bloque `{…}` antes de validar con `ForecastOutputSchema`.
- **Neutralidad al contenido:** el parser no altera *qué* probabilidad dice el modelo; solo la extrae. Las respuestas cacheadas en disco son intactas.
- **Run relanzado (histórico):** purga live + mismo comando — reanudación vía cache. **Desde 2026-07-15 tarde:** resume sin purga; `--fresh` solo si quieres empezar de cero.
- **Repair prompt insuficiente:** el diseño original reenviaba un repair si el schema fallaba, pero el repair también podía volver con fences; el parser directo cubre el caso que el repair no resolvía de forma fiable.
- **Prompt endurecido (mismo día):** `naive.txt` — **solo instrucciones de formato** (JSON puro, sin fences); bloque *Calibration instructions* sin cambios. Ver diff en git (`naive.txt`). Cambio de `promptHash` → las entradas cacheadas del prompt viejo **no** se reutilizan; el relanzamiento con purga exige miss + nueva llamada por pregunta. Run actual: un solo promptHash en `forecasts.prompt_hash` (sin mezcla viejo/nuevo).
- **sim-paper / sim-grid:** código existe (`sim-paper`, `sim-paper-grid` CLI) pero **fuera del bundle día D** — misma cuarentena conceptual que `sim_ganancias_eur.py`; exploración post-verdict con pre-reg propio (book, fricción real), no mid-only en el bundle del veredicto.

### Timeout cliente LLM (2026-07-15)

- `LLM_TIMEOUT_MS = 180_000` (3 min) por llamada en `src/pipeline/client.ts` (`fetchWithTimeout` + `AbortController`).
- Tras timeout: retry mismo modelo (hasta 8 intentos, backoff 2s×intento); si agota → `forecast_failed` en esa fila, el batch continúa.
- Sin timeout una llamada colgada bloquea el run entero — este guard evita descubrirlo a las 3 AM.

### Fix ingest CLOB — historial vacío (2026-07-15, pre-forecast)

- `prices-history` con `interval=1d` devolvía `history: []` para toda la muestra; `horizonSnapshotRejects: 1500` → 0 snapshots.
- **Fix:** `clob_prices.ts` usa `startTs`/`endTs` en chunks de 13 días; caches vacíos `[]` se tratan como miss.
- **Rehidratación:** 1471 snapshots, 481/500 preguntas con 3 horizontes completos (19 incompletas excluidas enteras del scoring).

### Stats de duración en cascada (2026-07-15)

- `durationDays.p50` en `ingest-cascade` se calculaba sobre binarios pre-filtro (mediana ~3,7 d con filtro `≥7d` activo).
- **Fix:** stats sobre población `afterDuration`; campo `population: "afterDuration"` en el reporte de cascada. Verificación: 0 preguntas elegibles con `duration_days < 7`.


Con `trainingCutoff: 2023-12-01` y universo principal `resolutionFrom: 2024-01-01`, la ventana de canarios \([cutoff-maxLag, cutoff-minLag]\) ≈ **2022-12-01 … 2023-10-02** queda **vacía** en el ingest principal. El detector de leakage quedaría ciego justo donde más importa (post-training puede extender conocimiento más allá del cutoff nominal).

**Fix congelado (pre-resultados legal):**

1. **`ingest-canaries`** — pull keyset suplementario `2022-12-01`–`2023-10-31`, **`targetCount: 25`**. Preguntas `canary_only=1`: excluidas de muestra y veredicto; incluidas en forecast/score solo para integridad.
2. **Canario temporal (held-in Q1 2024)** — tripwire si skill en preguntas resueltas `2024-01-01`–`2024-03-31` (held-in) > `0.15`. El held-out pobre es **esperado** pre-run (`BELOW_MARKET`); **no** forma parte del disparo.

Gate (`ingest-cascade`) exige `canarySupplementOk` (≥25 canarios) antes de `readyForForecast`.

### Semántica de lectura — tripwires vs veredicto

**Orden obligatorio al abrir `report.json`:** `integrity` primero → luego `verdict` → luego `metrics.skill`. Sin interpretación adicional.

| Señal | Tipo | Acción |
|-------|------|--------|
| `integrity.auditRequired: true` | **Tripwire** | Revisión manual de los items listados en `auditTriggers` **antes de publicar**. No invalida el veredicto de skill. |
| `canary_brier_low` | Tripwire | Auditar manualmente las N canarios (favoritas fáciles vs leakage real). |
| `canary_insufficient_n` | Tripwire | Completar supplement o auditar por qué faltan. |
| `temporal_q1_skill_high` | Tripwire | Auditar Q1 2024 held-in (~40–50 preguntas); firma posible de post-cutoff parcial. |
| `integrity.hardIntegrityFailure: true` | **Hard** | `EVAL_INVALID` — muestra eval contaminada (cutoff/eligibility). |

**N=25 canarios:** el canario con N fijo es un **tripwire de auditoría, no un test estadístico**. Su disparo obliga a revisión manual de los 25 items; **no** es invalidación irrevocable automática ni absolución automática si no dispara. Con N pequeño, Brier bajo puede ser azar (favoritas a 0.9) o alto por preguntas raras — ruidoso en ambas direcciones.

**No disparar ≠ limpio:** ausencia de tripwire no certifica ausencia de leakage; solo que no hubo señal en estos umbrales ruidosos.

## Auditoría en `report.json`

Cada report incluye `selection`: universo (modo, páginas, intersección), seed, estratos, modelos en intersección, N held-out/train tras split temporal, y `selection.composition` (heurística de slug + concentración temporal).

**Composición (pre-run, no bloqueante):**

- `selection.composition.slugHeuristics` es **cota inferior por patrón** (regex no excluyente). Subestima deportes con slugs de liga (`lal-`, `spl-`, `tur-`, `fl1-`, …). Si deportes resulta ~30–40% del elegible, el veredicto pondera fuerte mercados deportivos con plazo — declararlo al leer resultados.
- `selection.composition.temporalConcentration`: con ~85–90% del elegible en 2025, el veredicto es esencialmente sobre preguntas resueltas en 2025 (fiel al universo; legal con estratificación proporcional).
- `afterDateRange` al 100% en cascada = Gamma ya acota con `end_date_min/max` en keyset; la cascada re-verifica (defensa en profundidad).

**Campos de métricas en report:** Brier agregado, `brierByHorizon`, bins de calibración + ECE, canarios, contadores de integridad (`mixedModels`, `forecastFailedRate`, …).

## Expectativas pre-run (2026-07-15, antes del primer naive live)

**Veredicto esperado:** `BELOW_MARKET` o `MATCHES_MARKET` — el mercado agrega información que el forecaster NIM no replica; no esperamos `BEATS_MARKET` en v1.

**Por horizonte:** peor calibración/Brier vs mercado en T−24h; gap menor en T−7d (el mid de mercado lleva menos señal con más antelación). Si el resultado desafía esto, la primera hipótesis es bug o leakage, no genialidad del modelo.

## Persistencia forecast (apagar PC)

**Estado = `data/lab.sqlite` + `data/responses/`** (cache LLM). No hace falta copiar nada extra si esos archivos quedan en disco.

Antes de apagar (opcional, snapshot legible):

```powershell
.\scripts\save_forecast_state.ps1
```

Tras reiniciar:

```powershell
.\scripts\resume_forecast.ps1
```

O manual: `node dist/cli.js forecast-status` y el mismo `forecast` **sin** `--fresh`.

## v1.1 candidatos (no antes del veredicto v1)

- **`run_id` en `forecasts`/`scores`:** hoy resume es por `pipeline` + `model_id` (un solo run naive coexistiendo). Si v1.1 compara pipelines o re-runs en paralelo, añadir `run_id` — no antes.
- Resume + cache LLM: re-lanzar `forecast --mode live` tras interrupción salta filas existentes y reutiliza respuestas cacheadas (`model` + `promptHash`); solo paga API lo pendiente. `--fresh` borra filas `naive` en DB (no borra cache).
