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

| Guard | Resultado |
|-------|-----------|
| `signal_truncation_check` (16 pares cross-merge) | **OK** — 20+ cortes, warmup=220 |
| `recursive-analysis` | **OK** — sin lookahead en indicadores |

---

## Screen (#10, `--bias-controls`)

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

## MeanRevBB al cierre de implementación

| Campo | Valor |
|-------|-------|
| Lock | LOCKED (validación full activa) |
| Fase | WF ventana 0, epoch **78/300** (`strategy_MeanRevBB_2026-07-10_16-06-38.fthypt`) |
| `report.json` | No |

---

## Veredicto

**PASA confirmado (screen, intento #10)** — auditoría fees 2026-07-10: fricción real 16–45%, no cero; veredicto inalterado. Candidato en cola post-calibración MeanRevBB.

Si **DESCARTADA** en validación full: autopsia Freqtrade vs `research/xsec_lab.py` mismo timerange.

---

## Aislamiento del run vivo

**Grep imports MeanRevBB.py:** `quant_core`, `_base`, `talib`, `freqtrade` — **no** importa `XSecMomentum`, `xsec_momentum_core`, ni `screen_strategy.py`. Editar esos archivos no afecta el hyperopt MeanRevBB en curso.
