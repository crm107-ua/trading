# Hipótesis #14 — Funding Rate Carry: viabilidad técnica (Fase 0)

**Fecha:** 2026-07-13  
**Mecanismo (vinculante):** los longs apalancados en perpetuos pagan funding de forma sistemática; la estrategia cobra ese pago. Quién pierde: el especulador apalancado que paga por conveniencia de apalancamiento sin vencimiento.  
**Estado:** Fase 0 completada — **GO condicionado** (ver §6).  
**No se ha escrito estrategia Freqtrade.**

---

## Resumen ejecutivo

| Punto | Veredicto | Nota |
|-------|-----------|------|
| 1. Freqtrade + exchange futures | **GO** | 2026.6, `binanceusdm`, cross/isolated |
| 2. Funding histórico API ≥2 años | **GO** (líquidos) | BTC/ETH desde 2019; alts desde listing; DEXE solo 2024-12 |
| 3. Descarga funding en pipeline | **GO** | `download-data --candle-types funding_rate` + script research existente |
| 4. Coste estructura | **GO económico marginal** | Carry bruto histórico >> fees en majors; fricción alta en delta-neutral multi-pierna |
| 5. Arquitectura operativa | **CONDICIÓN** | Delta-neutral spot+perp **no** cabe en un solo bot Freqtrade |

**Veredicto global Fase 0:** **GO** — autoriza Fase 1 (pre-registro) con elección explícita de estructura y pipeline de validación acorde.

**Actualización 2026-07-13:** pre-registro congelado en `docs/PREREG_14_FUNDING_CARRY.md` — estructura **delta-neutral** vía simulador `research/`; universo whitelist 4 pares (≥4 años funding); presupuesto 6 h/semana, cierre 2026-08-31.

---

## 1. Soporte futures en Freqtrade + exchange

### Entorno verificado

| Componente | Valor |
|------------|-------|
| Imagen | `freqtradeorg/freqtrade@sha256:87aa5c6d65359b34e9d99a0bb260a38c0efe0315253811e6f48c2afe8f278a6a` |
| Versión | **Freqtrade 2026.6** |
| CCXT | **4.5.61** |
| Config actual del lab | `trading_mode: spot`, exchange `binance` (`user_data/config/base.json`) |

### Exchanges soportados (`list-exchanges`)

| Exchange | ID | Modos |
|----------|-----|-------|
| Binance | `binance` | spot, **cross futures**, **isolated futures** |
| Binance USDⓈ-M | `binanceusdm` | **cross futures**, **isolated futures** |

**Recomendación para #14:** `binanceusdm` + `trading_mode: futures` + `margin_mode: isolated` (o cross). El ID `binance` unificado también expone futuros vía `defaultType: swap`, pero el lab debe usar el mismo patrón que la documentación oficial (`binanceusdm`).

### Mercados

- Probe CCXT: **660** perpetuos USDT activos en `binanceusdm` (2026-07-13).
- `list-markets` con config probe (`user_data/config/probe_futures.json`): OK — pares `BASE/USDT:USDT`, tipo Future, apalancamiento hasta 125×.

### Config mínima futures (probe reproducible)

```json
{
  "trading_mode": "futures",
  "margin_mode": "isolated",
  "exchange": { "name": "binanceusdm", "pair_whitelist": ["BTC/USDT:USDT"] }
}
```

Archivo: `user_data/config/probe_futures.json` (telegram/api deshabilitados para CLI).

### Limitación arquitectónica crítica

**Una instancia Freqtrade = un solo `trading_mode`.** No puede operar simultáneamente long spot + short perp (delta-neutral clásico) en el mismo bot. Opciones:

| Estructura | Viabilidad Freqtrade nativa | Validación |
|------------|----------------------------|------------|
| **Short perp direccional** | Sí — un bot `futures` | Pipeline estándar (screen + WF + OOS) |
| **Delta-neutral spot + short perp** | No — requiere 2 piernas | Simulador `research/` dual-leg **o** dos bots coordinados (live); no encaja en el pipeline actual sin extensión |

Esto no es NO-GO global; fija la bifurcación obligatoria de Fase 1.

---

## 2. Funding rate histórico vía API

### Endpoint

`GET https://fapi.binance.com/fapi/v1/fundingRate`

| Campo | Valor |
|-------|-------|
| Autenticación | Pública |
| Paginación | `limit=1000`, `startTime` cursor |
| Granularidad | **8 h** (3 pagos/día) |
| Campos | `symbol`, `fundingTime`, `fundingRate`, `markPrice` |

### Profundidad histórica (probe 2026-07-13)

| Símbolo | Primer registro (desde 2019-09-01) | Filas 2021→2026 | Años efectivos |
|---------|-----------------------------------|-----------------|----------------|
| BTCUSDT | 2019-09-10 | 6 059 (~2 020 días) | **≥6 años** |
| ETHUSDT | 2019-11-27 | 6 059 | **≥6 años** |
| SOLUSDT | 2020-09-13 | 6 134 | **≥5 años** |
| BNBUSDT | 2020-02-10 | 6 059 | **≥5 años** |
| DEXEUSDT | 2024-12-24 | 3 395 (~1 132 días) | **<2 años** |

**Criterio lab (≥2 años):** cumple en perpetuos líquidos (BTC, ETH, BNB, SOL, etc.). Alts con listing tardío del perp (DEXE, otros fuera de E2) quedan fuera del universo o con historial acortado — misma lección que #11/#12.

### Estadísticas funding 2021-01-01 → 2026-07-01 (bruto, sin filtro de señal)

| Par | Media anualizada* | p90 anualizada | % periodos >0 | % periodos >0.01%/8h |
|-----|-------------------|----------------|---------------|------------------------|
| BTC | 10.9% | 18.4% | 85.6% | 12.4% |
| ETH | 11.7% | 23.0% | 84.0% | 13.5% |
| SOL | 0.8% | 22.7% | 71.2% | 13.1% |

\* `mean(funding_rate) × 3 × 365` — techo teórico si se estuviera short todo el tiempo; la estrategia solo entraría en regímenes altos (Fase 1).

**Nota histórica del lab:** #11 y #12 usaron funding como señal para **spot** con signo contrario al esperado. #14 es mecanismo distinto (cobrar carry en perp, no momentum ni predicción spot).

---

## 3. Descarga de funding en Freqtrade vs pipeline externo

### Opción A — Freqtrade `download-data` (**verificado**)

```bash
docker compose run --rm freqtrade download-data \
  --config user_data/config/probe_futures.json \
  --pairs BTC/USDT:USDT \
  --timerange 20240101-20240115 \
  --trading-mode futures \
  --candle-types funding_rate
```

Resultado: `user_data/data/binanceusdm/futures/BTC_USDT_USDT-1h-funding_rate.feather` (14 KB, 1000 filas en rango de prueba).

CLI relevante:

- `--trading-mode {spot,margin,futures}`
- `--candle-types … funding_rate` (default futures incluye `futures`, `funding_rate`, `mark`)

### Opción B — Pipeline research existente

- Script: `research/download_funding_local.py`
- Destino: `research/data_local/funding/` + `funding_manifest.json`
- Documentado en `docs/data_sources.md` (descarga 2026-07-11, 16/16 E2)

### Uso en backtest Freqtrade

El motor de backtest **carga funding rates** y aplica `_run_funding_fees` / `calculate_funding_fees` en modo futures (`backtesting.py`, `binance.py`). No hace falta SQLite externo para simular funding en perps dentro de Freqtrade.

### Recomendación

| Uso | Fuente |
|-----|--------|
| Backtest / screen Freqtrade futures | `download-data` → datadir `binanceusdm` |
| Research agregado, event studies, delta-neutral dual-leg | `research/download_funding_local.py` (ya probado en #11/#12) |
| Señal en estrategia futures | Columnas OHLCV + funding mergeado por dataprovider (nativo en futures mode) |

**No se requiere pipeline SQLite externo** salvo que se elija delta-neutral fuera de Freqtrade.

---

## 4. Coste de estructura (cuenta de referencia: 10 000 USDT)

*Tamaño no especificado por el usuario; se usa `dry_run_wallet: 10000` del lab como referencia. Recalcular en Fase 1 si el capital real difiere.*

### Comisiones Binance (VIP 0, conservador — taker)

| Pierna | Fee/lado |
|--------|----------|
| Spot | 0.10% |
| USDT-M perp | 0.05% |

### A) Short perp direccional (1 pierna)

| Concepto | Coste estimado |
|----------|----------------|
| Apertura + cierre perp | 0.05% × 2 = **0.10%** del notional |
| Slippage (majors líquidos) | **0.05–0.10%/lado** (vs 0.56%/lado en XSec iliquido, #13-F) |
| Slippage (alt E2 medio) | **0.20–0.56%/lado** |
| Funding | **Ingreso** (si rate > 0 y short); modelado en backtest FT |
| Riesgo precio | **No delta-neutral** — exposición direccional short |

**Ejemplo 10 000 USDT, 1× notional, majors, slippage 0.10%/lado:**

- Fricción ida+vuelta ≈ 0.10% fees + 0.40% slippage ≈ **0.50%** → **~50 USDT** por ciclo completo.
- Carry bruto en regímenes altos (p90 ~18–23% anualizado en BTC/ETH) puede superar fricción si la permanencia media es de **semanas**, no días — umbral exacto se fija en pre-registro (Fase 1).

### B) Delta-neutral spot long + short perp (2 piernas)

| Concepto | Coste estimado |
|----------|----------------|
| Abrir ambas piernas | 0.10% spot + 0.05% perp = **0.15%** |
| Cerrar ambas piernas | **0.15%** |
| Round-trip total fees | **~0.30%** |
| Slippage (4 ejecuciones, majors) | **+0.20–0.40%** |
| **Total ciclo** | **~0.50–0.70%** del capital desplegado |
| Capital | ~50% spot + margen perp (mismo notional) → sobre 10k, **~5k por pierna** efectiva |

**Breakeven ilustrativo:** con funding medio **0.03%/día** (≈11% anual) durante **20 días** → +0.60% bruto ≈ cubre un ciclo. Permanencias cortas o funding que cae por debajo del umbral erosionan el edge — condición de muerte pre-escrita en Fase 1.

### Funding neto vs costes

En majors, el funding histórico medio (siempre short) supera ampliamente 0.50% por ciclo. La pregunta empírica no es «¿hay funding?» sino «¿los regímenes filtrados (señal Fase 1) dejan suficiente permanencia y magnitud tras fricción realista?». Eso es validable; no bloquea Fase 0.

---

## 5. Riesgos y lecciones del lab

| ID | Riesgo | Mitigación Fase 1 |
|----|--------|-------------------|
| R-11 | Signo funding vs spot (#11 invertido) | #14 no predice spot; cobra funding en perp |
| R-13E | Concentración PnL (ZEC 60%) | Condición de muerte: >40% PnL en un activo |
| R-13F | Slippage ~0.56%/lado en rotación iliquida | Universo liquidez objetivo; majors para probe inicial |
| R-FT | Delta-neutral no nativo | Elegir estructura única en pre-registro; no mezclar pipelines |
| R-DEXE | Perp listing tardío | Excluir pares con <2 años de funding |

---

## 6. Veredicto Fase 0

### **GO** — proceder a Fase 1 (`docs/PREREG_14_FUNDING_CARRY.md`)

**Justificación:**

1. Stack instalado soporta futuros Binance USDⓈ-M de forma oficial.
2. API de funding con historial suficiente para split IS/OOS en perpetuos líquidos.
3. Dos vías de datos operativas (Freqtrade datadir + research script).
4. Carry bruto histórico en majors es del orden de magnitud necesario; fricción es el rival principal, no la ausencia de dato.
5. No hay bloqueante técnico absoluto.

**Condiciones vinculantes para Fase 1:**

1. **Elegir UNA estructura** antes de ver resultados:
   - *Short perp direccional* → validación con pipeline Freqtrade existente.
   - *Delta-neutral* → pre-registrar simulador dual-leg en `research/` (o extensión explícita del pipeline); **no** asumir paridad con screen Freqtrade spot.
2. **Universo:** solo pares con ≥2 años de funding **y** criterio de liquidez pre-fijado.
3. **Presupuesto tiempo/fecha límite:** pendiente de rellenar por el usuario antes de lanzar validación.
4. **Sin hyperopt** sobre umbrales de señal (regla del proyecto).

### NO-GO explícito descartado

- No se cierra #14 en registry.
- No se bloquea por falta de API, versión Freqtrade, ni imposibilidad de descargar funding.

---

## Anexo — Comandos de reproducción

```bash
# Versiones
docker compose run --rm freqtrade --version

# Exchanges
docker compose run --rm freqtrade list-exchanges

# Mercados futures
docker compose run --rm freqtrade list-markets \
  --config user_data/config/probe_futures.json --quote USDT --trading-mode futures

# Descarga funding
docker compose run --rm freqtrade download-data \
  --config user_data/config/probe_futures.json \
  --pairs BTC/USDT:USDT ETH/USDT:USDT \
  --timerange 20210101- \
  --trading-mode futures \
  --candle-types funding_rate mark futures
```

---

*Siguiente paso autorizado: Fase 1 — pre-registro congelado antes de cualquier backtest de señal.*
