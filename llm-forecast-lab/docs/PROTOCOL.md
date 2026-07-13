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
- **v1 un solo modelo:** `gpt-4.1-mini` en `models.json`. Sin fallback entre modelos; 429 → retry mismo modelo → `forecast_failed`. Guard `mixed_models` en report.
- **NIM:** fuera de v1 (v1.1 como modelos de primera clase con cutoff propio).

## Auditoría en `report.json`

Cada report incluye `selection`: universo (modo, páginas, intersección), seed, estratos, modelos en intersección, N held-out/train tras split temporal, y `selection.composition` (heurística de slug + concentración temporal).

**Composición (pre-run, no bloqueante):**

- `selection.composition.slugHeuristics` es **cota inferior por patrón** (regex no excluyente). Subestima deportes con slugs de liga (`lal-`, `spl-`, `tur-`, `fl1-`, …). Si deportes resulta ~30–40% del elegible, el veredicto pondera fuerte mercados deportivos con plazo — declararlo al leer resultados.
- `selection.composition.temporalConcentration`: con ~85–90% del elegible en 2025, el veredicto es esencialmente sobre preguntas resueltas en 2025 (fiel al universo; legal con estratificación proporcional).
- `afterDateRange` al 100% en cascada = Gamma ya acota con `end_date_min/max` en keyset; la cascada re-verifica (defensa en profundidad).

**Campos de métricas en report:** Brier agregado, `brierByHorizon`, bins de calibración + ECE, canarios, contadores de integridad (`mixedModels`, `forecastFailedRate`, …).

## Expectativas pre-run (2026-07-13, antes del primer naive live)

**Veredicto esperado:** `BELOW_MARKET` o `MATCHES_MARKET` — el mercado agrega información que el LLM naive no replica; no esperamos `BEATS_MARKET` en v1.

**Por horizonte:** peor calibración/Brier vs mercado en T−24h; gap menor en T−7d (el mid de mercado lleva menos señal con más antelación). Si el resultado desafía esto, la primera hipótesis es bug o leakage, no genialidad del modelo.
