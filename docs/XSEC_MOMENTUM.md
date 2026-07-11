# XSecMomentum — intento #10 (P1)

**Hipótesis:** momentum cross-sectional 1d, top-3, rebalanceo semanal (lunes), universo ancho E2, filtro BEAR BTC.  
**Research de referencia:** E2 intento #7 — 10.4x baseline / 7.1x leave-one-out vs 2.5x equal-weight (controles en `research/output/bias_controls_20260710.json`).

---

## Tesis

Rotación equiponderada entre los N pares con mayor momentum lookback, rebalanceando solo los lunes, sin entradas en régimen BEAR y salida plana en BEAR. La gestión de riesgo primaria es la rotación + filtro de régimen, no stops ATR.

---

## Universo (16 pares USDT, E2)

| Par | Inicio datos 1d | Velas (2026-07-09) |
|-----|-----------------|---------------------|
| AAVE/USDT | 2021-01-01 | 2016 |
| ADA/USDT | 2021-01-01 | 2016 |
| BNB/USDT | 2021-01-01 | 2016 |
| BTC/USDT | 2021-01-01 | 2016 |
| DEXE/USDT | 2021-07-23 | 1813 |
| DOGE/USDT | 2021-01-01 | 2016 |
| ETH/USDT | 2021-01-01 | 2016 |
| LTC/USDT | 2021-01-01 | 2016 |
| NEAR/USDT | 2021-01-01 | 2016 |
| SKL/USDT | 2021-01-01 | 2016 |
| SOL/USDT | 2021-01-01 | 2016 |
| TRX/USDT | 2021-01-01 | 2016 |
| UNI/USDT | 2021-01-01 | 2016 |
| XLM/USDT | 2021-01-01 | 2016 |
| XRP/USDT | 2021-01-01 | 2016 |
| ZEC/USDT | 2021-01-01 | 2016 |

Config: `user_data/config/screen_xsec.json` (`max_open_trades: 3`).

---

## Desviaciones del motor pandas (obligatorias / documentadas)

| Motor pandas | Freqtrade XSecMomentum | Por qué |
|--------------|------------------------|---------|
| Cartera log-return continua | Trades discretos por par | Freqtrade es event-driven por par |
| Sin stop | `stoploss = -0.35` fijo, `use_custom_stoploss=False` | Emergencia; pandas no tenía stop |
| Régimen implícito en research | BEAR vía `add_regime_indicators` en **BTC 1d** | Freqtrade exige informative TF ≥ strategy TF; `_base` fija BTC@4h → incompatible con 1d nativo sin tocar `_base.py` |
| Clasificador BEAR “validado” (`_base` BTC@4h) | **Clasificador variante BTC@1d** — misma fórmula EMA200+ADX, otro timeframe | **No es el clasificador validado del lab.** Truncation/recursive cubren causalidad, no equivalencia de comportamiento. Validación full debe tratarlo como pieza nueva. |
| Hereda QuantBaseStrategy | Hereda **IStrategy** | Evita `@informative("4h")` del padre en estrategia 1d |
| Universo vía panel pandas | Merge manual `dp.get_pair_dataframe` por par 1d | Sin informative 1d→1d (rechazado por Freqtrade) |
| Rebalanceo W-FRI (research) | **Lunes** fijo (`REBALANCE_WEEKDAY=0`) | Pre-registrado; E4 descartó estacionalidad |

---

## Guards (datos reales, 2024)

| Guard | XSecMomentum (#10) | XSecMomentum20M (2026-07-11) |
|-------|-------------------|------------------------------|
| `signal_truncation_check` (16 pares cross-merge) | **OK** — 20+ cortes, warmup=220 | **OK** — 20+ cortes, warmup=220 |
| `recursive-analysis` | **OK** — sin lookahead en indicadores | **OK** — sin variación por startup candle |

Configs guards: `base.json` + `backtest.json` + `screen_xsec.json`, timerange `20240101-20240320`.

---

## XSecMomentum20M — implementación filtro liquidez (2026-07-11)

Materialización del pre-registro candidato #10 / research #13. **No es intento nuevo.**

### Código

| Pieza | Ubicación |
|-------|-----------|
| Función pura máscara | `liquidity_eligibility_mask()` en `xsec_momentum_core.py` — MM30 vol. quote, `shift(1)`, umbral 20M |
| Vol. quote | `quote_volume_usdt(volume, close)` ≈ `volume × close` (misma aprox. que `r2_liquidity_filter.py`) |
| Ranking | `build_pair_ranks(..., asset_eligibility=...)` — no elegible → NaN (fuera del top) |
| Salida liquidez | `custom_exit` → `xsec_liquidity_exit` en rebalanceo si pierde elegibilidad (≡ desaparece del top en pandas) |
| Estrategia | `XSecMomentum20M(XSecMomentum)` — solo activa filtro; madre intacta como control |
| Constantes congeladas | `LIQUIDITY_WINDOW=30`, `LIQUIDITY_THRESHOLD=20e6`, `LIQUIDITY_MIN_PERIODS=20` — no hyperopt |

### Paridad research ↔ Freqtrade

`research/verify_20m_parity.py` sobre datos 1d E2 (`user_data/data/binance`): **0 discrepancias** en 16 pares (máscara elegible fecha a fecha vs `r2_liquidity_filter.py`).

### Tests

| Suite | Resultado |
|-------|-----------|
| `tests/test_xsec_liquidity_core.py` | 6/6 — causalidad, borde umbral, cruce entrada/salida |
| `tests/test_xsec_momentum_core.py` | 6/6 |
| `tests/test_xsec_momentum20m_fixture.py` | 2/2 — BNB sintético cruza 20M, opera y sale por rotación/liquidez |

---

## Screen confirmación 20M (`run_id=20260711_092654`)

**Timerange:** `20210101-` · **Control importado:** screen #10 `research_baseline` (sin filtro, zip re-parseado con fees corregidas).

| Variante | Trades | Net | Bruto | Fees | Fricción | Max DD | LOO bruto | ¿Pasa rotación? |
|----------|--------|-----|-------|------|----------|--------|-----------|-----------------|
| research_baseline (control #10) | 350 | +40 641 | +48 495 | 7 854 | 16.2% | 52.9% | +23 006* | **Sí** (importado) |
| **liquidity_20m_primary** | 325 | +17 201 | +21 904 | 4 702 | 21.5% | 46.3% | **−1 631** | **No** (LOO ≤ 0) |

\*LOO bruto del control: cifra corregida post-auditoría fees (JSON original subestimaba fees LOO).

**Veredicto screen global:** `PASA` solo porque el control importado cumple — la variante **primaria 20M no pasa** (LOO bruto negativo al excluir SOL/USDT).

**No se ajustó umbral ni parámetros** — conforme al pre-registro.

### Curva Freqtrade vs pandas (mismo timerange conceptual)

| Motor | Múltiplo wealth | Notas |
|-------|-----------------|-------|
| pandas E2 + filtro 20M (B) | **15.6×** | `research/output/r2_liquidity_filter.json` |
| pandas E2 sin filtro (B) | 12.25× | research #13 |
| Freqtrade **liquidity_20m_primary** | **~2.7×** net (10k→27k) | 325 trades, BEAR 1d, stop −35% |
| Freqtrade control sin filtro | **~5.1×** net (10k→51k) | screen #10 |

**Divergencia > 2×** en ambas direcciones: Freqtrade 20M **no replica** el uplift pandas (15.6× vs 2.7×); además el filtro **reduce** retorno Freqtrade vs control (opuesto al patrón monótono pandas 12.25→15.6×). Hipótesis operativa: implementación fiel en elegibilidad, pero mecánicas Freqtrade (3 slots, trades discretos, BEAR 1d, stop, dominancia SOL vs DEXE) impiden extrapolar el múltiplo research.

**Autopsia LOO 20M:** par dominante SOL/USDT; al excluirlo el bruto colapsa — concentración distinta al control (DEXE). Coherente con filtro que redirige rotación hacia large-caps líquidos.

Reporte: `user_data/validation_reports/screen/XSecMomentum20M/20260711_092654/screen_report.json`

### Estado validación full (congelado)

| Rol | Config | Screen confirmación |
|-----|--------|---------------------|
| **Primaria** | XSecMomentum20M, filtro dinámico 20M | **Implementada; screen NO PASA; autopsia 2026-07-11 → degradada (ii)** |
| **Control** | XSecMomentum sin filtro (#10) | PASA (screen #10) — **única config validación full** |

WF protocolo: 100 epochs según cola post-MeanRevBB.

---

## Autopsia 20M (2026-07-11)

**Anomalía:** máscara idéntica (paridad 0) pero el filtro **mejora** en pandas (12.25×→15.6×) y **destruye** en Freqtrade (5.1×→2.7×).

### H0 — hipótesis en competencia

| ID | Hipótesis | Resultado |
|----|-----------|-----------|
| **H-frágil** | El efecto 20M depende de SOL; pandas colapsaría en LOO ex-SOL | **Rechazada** — pandas 20M ex-SOL: **12.35×** (>EW filtrado 1.25×); mejora +51% vs sin filtro ex-SOL (8.15×) |
| **H-mecánica** | Desviación de ejecución Freqtrade invierte el beneficio | **Parcial** — ablación no invierte el filtro en pandas; slots discretos comprimen múltiplo absoluto (15.6→7.0) y margen relativo (27%→4.6%) |

### A — LOO ex-SOL (pandas)

| Config | Wealth B ex-SOL | vs EW ex-SOL |
|--------|-----------------|--------------|
| 20M filtro | **12.35×** | > 1.25× ✓ |
| Sin filtro | 8.15× | — |
| EW filtrado 20M | 1.25× | criterio H-frágil |

La fragilidad-SOL es **específica de Freqtrade** (LOO bruto −1.6k), no del motor pandas.

### B — Ablación mecánica (pandas, acumulativa)

| Paso | 20M B | Sin filtro B | ¿Filtro mejora? | Margen relativo |
|------|-------|--------------|-----------------|-----------------|
| 0 continuo | 15.60× | 12.25× | Sí | +27% |
| 1 slots discretos | 7.00× | 6.70× | Sí | +4.6% |
| 2 + BEAR flat | 13.12× | 9.54× | Sí | +37% |
| 3 + stop −35% | 15.37× | 14.51× | Sí | +5.9% |
| 4 + liq. exit | 15.37× | 14.51× | Sí | +5.9% |

**Ningún paso invierte** el beneficio del filtro en pandas. No reproduce 2.7× vs 5.1× de Freqtrade.

### C — Forense trades (zips existentes)

| Métrica | Control #10 | 20M |
|---------|-------------|-----|
| PnL DEXE+ZEC | **+26 055 + ZEC** ≈ +26k+ | **0** (filtrados) |
| PnL SOL | +15 279 | **+19 025** (dominante) |
| Exit `xsec_liquidity_exit` | — | **1** (casi nulo) |
| Exit `stop_loss` | 155 (44%) | 137 (42%) |

**Causa raíz Freqtrade:** el filtro elimina correctamente pares iliquidos que el **control** explotaba en PnL discreto (DEXE ≈ +26k). El 20M redirige hacia SOL; LOO ex-SOL falla. No es defecto de máscara ni de `xsec_liquidity_exit`.

### Recomendación: **(ii)**

Mantener **control #10 sin filtro** como única config de validación full. Degradar **primaria 20M** a descartada-por-materialización (implementación fiel, efecto invertido en Freqtrade por composición de cartera, no reparable sin cambiar hipótesis).

No proceder con fix de slots/relleno — la ablación muestra cash drag bajo en pandas (~1% semanas incompletas); la inversión viene de **qué pares** se operan, no de huecos vacíos.

Artefactos: `research/output/autopsy_20m_20260711.json`, `research/output/autopsy_20m_ablation.png`

---

**Timerange screen:** `20210101-` → datos hasta **2026-07-09** (ventana completa protocolo). Primer trade **2021-08-10** (warmup ~220 velas 1d). Último cierre **2026-06-02**.

**Configs mergeados:** `base.json` + `backtest.json` + `screen_xsec.json` — `fee: 0.001` confirmado en zip archivado (`*_config.json`).

Criterios: `docs/screen_protocol.md` sección rotación (estándar + LOO bruto>0 + max DD < 60%).

### Auditoría de fees (2026-07-10)

| Pregunta | Resultado |
|----------|-----------|
| ¿Backtest sin fricción? | **No** — `fee: 0.001` en config archivado del zip baseline |
| ¿Fees ~0 en reporte? | **Bug del parser** — `fee_open`/`fee_close` son **ratios**, no USDT; el screen sumaba 0.001×350≈0.70 |
| Fees reales baseline | **~7 854 USDT** (350 trades, stake variable) |
| Fricción real baseline | **16.2%** del bruto (7 854 / 48 495) — **< 50%** → criterio sigue cumpliéndose |
| ¿Repetir screen? | **No** — veredicto inalterado tras recálculo; fix en `screen_strategy.py` `_total_fees_from_trades` |

### Freqtrade vs pandas (mismo universo, `2021-01-01` → `2026-07-09`, w14 top-3 W, fee 0.1%/turnover)

| Motor | Retorno | Max DD | Notas |
|-------|---------|--------|-------|
| `xsec_lab.py` | **10.37×** wealth | −88.7% | Cartera única, log-returns |
| Freqtrade baseline | **~5.1×** wallet (10k→50.6k net) | −52.9% | 3 slots, trades discretos, BEAR 1d |

Freqtrade **no** supera al pandas en múltiplo — el +40k absoluto enmascaraba la comparación. La divergencia es **menor** retorno Freqtrade con **menor** DD reportado (mecánicas distintas + filtro BEAR + stop −35%).

**DEXE/USDT:** ~64% del PnL neto baseline (+26k de +40.6k). LOO sin DEXE: **+17.4k neto** (~5.6k fees → bruto ~23k). Cifra de referencia: efecto sobrevive sin DEXE, pero liquidez/slippage real en par exótico es riesgo de implementación.

Variantes: `user_data/fixtures/screen_variants/XSecMomentum.json`

| Variante | w | top_n | exit_rank_k |
|----------|---|-------|-------------|
| research_baseline | 14 | 3 | 4 |
| conservative | 30 | 2 | 4 |
| wide | 7 | 4 | 5 |

### Resultados (`run_id=20260710_162559`) — métricas corregidas (fees)

| Variante | Trades | Net | Bruto | Fees | Fricción | Max DD | LOO net | LOO bruto | ¿Pasa? |
|----------|--------|-----|-------|------|----------|--------|---------|-----------|--------|
| research_baseline | 350 | +40 641 | +48 495 | 7 854 | 16.2% | 52.9% | +17 414 | +23 006 | **Sí** |
| conservative | 198 | +66 522 | +68 835 | 2 313 | 3.4% | 66.1% | −650 | +908 | No (DD + LOO) |
| wide | 446 | +2 975 | +5 388 | 2 413 | 44.8% | 52.5% | +3 599 | +6 177 | **Sí** |

**Veredicto screen:** **PASA confirmado** (intento #10) — fees auditadas; fricción real < 50%; LOO y DD según protocolo rotación.

**Cola:** validación full **detrás** de calibración MeanRevBB. No lanzar `run_validation` ahora.

---

## Pre-registro validación full (2026-07-11, congelado antes de `report.json` MeanRevBB)

Basado en research día 2 (`research/results_20260711.md`, intento #13 PASA).

| Rol | Qué se valida |
|-----|----------------|
| **Configuración primaria** | **XSecMomentum-20M** — mismo motor screen (#10) + **filtro liquidez dinámico** |
| **Control** | XSecMomentum E2 **sin filtro** (screen #10) — comparación, no hipótesis operativa post-#13 |

### Regla de liquidez (obligatoria en implementación)

- **Dinámico en cada rebalanceo** (lunes): volumen quote USDT = `volume × close` del par.
- Ventana: **media móvil 30 días**, desplazada **1 día** (solo historia ≤ t−1, point-in-time).
- Umbral fijo: **> 20_000_000 USDT/día** (pre-fijado en intento #13, no optimizable).
- Solo los pares elegibles ese día compiten en el ranking momentum top-3.

**Prohibido:** universo estático (lista fija de pares que superan 20M de media histórica completa) — eso **no** replica el research (`research/r2_liquidity_filter.py`) y cambiaría la hipótesis.

### Evidencia que motiva primaria > control

| Métrica | E2 sin filtro (B) | E2 filtro 20M (B) |
|---------|-------------------|-------------------|
| Full | 12.25× | **15.60×** |
| Mitad 2024-26 | 7.48× (concentrado DEXE/ZEC) | **4.69×** (bate EW y BTC) |
| R0 ex-DEXE/ZEC 2024-26 | 1.13× (asterisco) | resuelto por 20M |

Patrón monótono en umbrales pre-fijados (5M→20M→50M: 6.4×→15.6×→21.9×): firma de efecto real, no umbral afortunado.

### OBS-11a (candado)

Funding caliente → retornos mejores (signo invertido vs #11). **No explotar.** Ver `docs/hypothesis_registry.md` sección observaciones bloqueadas.

Reporte screen original: `user_data/validation_reports/screen/XSecMomentum/20260710_162559/screen_report.json`  
**Fallo-en-vacío #9:** parser de fees sumaba ratios; sanity-check en `screen_strategy.py`.

---

## MeanRevBB al cierre de implementación (2026-07-11 ~11:35 UTC+2)

| Campo | Valor |
|-------|-------|
| Lock | **LOCKED** — `run_id=20260709_162954`, pid **16944** |
| Fase | WF ventana 0 — `.fthypt` ~70 MB (`strategy_MeanRevBB_2026-07-11_08-58-25.fthypt`), **~65–110/300** epochs (estimado) |
| Heartbeat | Último audit `2026-07-11T08:58:17Z` |
| `report.json` | No |

**Aislamiento:** `MeanRevBB.py` no importa estrategias XSec ni `screen_strategy.py`. Nada del run vivo modificado en `pipeline/`, `_base.py`, `quant_core.py`, `MeanRevBB.py`, configs base ni `hyperopt_results/`.

---

## Veredicto

**PASA confirmado (screen, intento #10, sin filtro)** — auditoría fees 2026-07-10. Candidato control en cola post-calibración MeanRevBB.

**XSecMomentum20M (primaria):** implementación + paridad máscara **OK**; screen **NO PASA** (LOO); autopsia 2026-07-11 confirma inversión por composición (DEXE filtrado), no por bug de máscara — **degradada**; validar solo control #10.

Si **DESCARTADA** en validación full: autopsia Freqtrade vs `research/xsec_lab.py` mismo timerange.

---

## Aislamiento del run vivo

**Grep imports MeanRevBB.py:** `quant_core`, `_base`, `talib`, `freqtrade` — **no** importa `XSecMomentum`, `xsec_momentum_core`, ni `screen_strategy.py`. Editar esos archivos no afecta el hyperopt MeanRevBB en curso.
