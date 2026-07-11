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
| Sin stop | `stoploss = -0.35` en clase; **screen materializa −0.1** vía `PARAMS_TEMPLATE` | Emergencia; ver reconciliación 13-D |
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

## Reconciliación motores 13-D (2026-07-11)

**Pregunta:** la ablación 13-B no reprodujo Freqtrade (pandas 15.37×/14.51× vs FT 2.7×/5.1×). Objetivo: nombrar el gap y explicar la anomalía de stops.

### Parte 1 — Anomalía stops (zip control #10, 350 trades)

| Exit reason | N | PnL% medio | Duración mediana | PnL abs sum |
|-------------|---|------------|------------------|-------------|
| `stop_loss` | 155 | **−10.17%** (todos ~−10%) | **2 días** | −198 615 |
| `xsec_rotation_exit` | 173 | +11.6% | **14 días** | +203 190 |
| `xsec_bear_flat` | 22 | +21.1% | 7 días | +36 066 |

- **Los 155 stops NO pierden −35%** — salen a **−10.18%** (`stop_loss_ratio = −0.1`).
- **Causa:** `user_data/tools/screen_strategy.py` → `PARAMS_TEMPLATE` escribe `"stoploss": -0.1` en `XSecMomentum.json`, anulando `stoploss = -0.35` de la clase. El screen PASA (#10) operó con **−10%**, no −35% documentado.
- **Rotación no rota:** 173 salidas por rotación (mediana 14 días); solo 11/155 stops tuvieron rank>4 en algún lunes previo. El perfil extremo de stops era **lectura errónea del nivel** (−10% en ~2 días, no −35% en semanas).
- **PnL neto +40.6k:** patrón «muchos stops pequeños (−199k) vs cohetes (+239k)» — no dominancia de stops.
- **Screen PASA:** validez **comprometida** en dimension stop (defecto de materialización, no bug de rotación).

### Parte 2 — Ablación fidelidad incremental (control sin filtro)

Motor: `simulate_freqtrade_fidelity()` en `research/xsec_lab.py` + `research/motor_reconciliation.py`.  
Referencia FT: zip `backtest-result-2026-07-10_16-26-23` → **5.06×** (10k→50.6k).

| Paso | Mecánica | Múltiplo | Δ mult | Corr. sem. vs FT |
|------|----------|----------|--------|------------------|
| 0 | Research W-FRI log continuo (B) | 10.37× | — | 0.01 |
| 1 | Lunes señal + 3 slots; **ejecución martes open** | 7.22× | −3.15 | 0.06 |
| 2 | Entrada open t+1 (redundante con martes) | 7.22× | 0 | 0.06 |
| 3 | Fees 0.1% por lado | 7.11× | −0.11 | 0.06 |
| 4 | Stop −10% intradía (low) | 6.41× | −0.71 | 0.09 |
| 5 | Compounding stake = wallet/3 | 8.24× | +1.84 | 0.10 |
| 6 | PIT DEXE (2021-07-23) | 8.24× | 0 | 0.10 |
| **FT control** | — | **5.06×** | — | 1.00 |

**Criterio éxito** (corr. semanal >0.9, múltiplo ±30%): **no alcanzado** — gap residual **1.63×** (8.24 vs 5.06).

**Gap con nombre (dos capas):**

1. **Motor research optimista (~2.0×):** log-continuo W-FRI sin slots → 10.37× vs FT 5.06×. Factor de corrección instrumento: **~2.05×** (research/FT).
2. **Infidelidad residual (~1.63×):** tras las 6 mecánicas, el simulador aún sobreestima. Sospechosos no modelados: `evaluate_min_stake_policy` (rechazos de entrada), `confirm_trade_entry` (re-check BEAR en martes), ADX/EMA200 vía `ta-lib` vs aproximación pandas en `compute_btc_regime_daily`, merge informative por par (rank puede diferir del panel global — primera divergencia sostenida **2021-08-16**: FT ETH/SOL/UNI vs sim DOGE/SOL/XRP).

**Clasificación por mecánica:**

| Mecánica | Tipo | Efecto |
|----------|------|--------|
| W-FRI → lunes/martes + slots | Coste real de ejecutar | −30% mult |
| Fees por lado | Coste real | −1.5% |
| Stop −10% intradía | Coste real + **defecto materialización** (nivel screen ≠ clase) | −10% |
| Compounding wallet/3 | Coste real (parcialmente modelado) | +29% (sobrecompensa vs FT — stake policy no capturada) |
| PIT DEXE | Neutro en este timerange | 0 |

### Re-evaluación degradación 20M (modo fidelidad final)

| Config | Múltiplo modo fidelidad |
|--------|-------------------------|
| Sin filtro | **8.24×** |
| Filtro 20M | **1.66×** |

El filtro **sigue empeorando** en motor reconciliado (como Freqtrade 5.1→2.7) → degradación primaria 20M **confirmada con mecanismo**, no prematura.

### Regla instrumento (#14+)

> Criterios de `xsec_lab` en modo log-continuo W-FRI (B) sobreestiman ~**2×** vs Freqtrade. Todo screen research debe validarse también en `simulate_freqtrade_fidelity` (modo 6_pit_dexe). Umbral mínimo: múltiplo fidelidad dentro de ±30% del zip Freqtrade de referencia.

Artefactos: `research/output/motor_reconciliation_20260711.json`, `research/output/motor_reconciliation_20260711.png`

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

**Riesgo abierto (13-E):** el múltiplo absoluto Freqtrade contiene un factor **~3.6×** no reconciliado con el instrumento (`diagnose_m35_13e_20260711.json`). El veredicto full debe apoyarse en **métricas relativas y de estabilidad** (WFE, % ventanas positivas, DD, LOO), **no en el múltiplo** — para que un 26× no deslumbre la lectura.

**Dry-run:** arrancado bajo `docs/dryrun_protocol.md` — reloj de brecha activo; datos solo para comparador post-veredicto.

Basado en research día 2 (`research/results_20260711.md`, intento #13 PASA).

| Rol | Qué se valida |
|-----|----------------|
| **Configuración primaria** | **XSecMomentum-20M** — **degradada** (13-E); no validar |
| **Control** | **XSecMomentum-m35** (`stop_design_m35`, 10-RS) — única config validación full |

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
**Fallo-en-vacío #10:** `PARAMS_TEMPLATE` forzaba `stoploss: -0.1` — ver sección siguiente.

---

## Fallo-en-vacío #10 — stop no pre-registrado (2026-07-11)

El screen PASA (#10) materializó **stop −10%** vía JSON de variante, no el **−35%** documentado en `XSecMomentum.py`.

| Item | Detalle |
|------|---------|
| Causa | `screen_strategy.py` → `PARAMS_TEMPLATE` hardcodeaba `stoploss: -0.1` |
| Fix | `build_params_template()` lee stop de clase; override explícito `stoploss` en variante |
| Tests | `test_build_variant_params_respects_xsec_class_stoploss` |
| Auditoría | `research/audit_screen_stops.py` → `screen_stop_audit_20260711.json` |
| Re-screen Docker | **Hecho** — `run_id=20260711_100039` (ventana 1 estable, ~6 epochs) |
| Veredicto #10 | **PASA rehabilitado (10-RS)** — ambos stops pasan; validación full = **m35** |

**Radiografía edge (zip control accidental m10):** −199k stops / +203k rotaciones / +36k BEAR — edge fino bajo −10%; con m35 el perfil mejora (menos stops, mayor neto).

---

## Re-screen 10-RS (`run_id=20260711_100039`, 2026-07-11)

**Desenlace: pasan ambos stops** — candidato robusto al nivel del stop.

| Variante | Stop | Trades | Net | Bruto | Fricción | Max DD | LOO excl. | LOO bruto | ¿Pasa rotación? |
|----------|------|--------|-----|-------|----------|--------|-----------|-----------|-----------------|
| **stop_design_m35** | **−0.35** | 296 | **+252 092** | +260 761 | 3.3% | **45.6%** | ZEC | **+77 617** | **Sí** |
| stop_accidental_m10 | −0.10 | 350 | +40 641 | +48 495 | 16.2% | 52.9% | DEXE | +23 006 | Sí (insensibilidad) |

Stops materializados en zip: −0.35 y −0.10 verificados. Screen #10 original anulado.

**Config validación full:** `stop_design_m35` (diseño documentado). m10 no se elige por +41k histórico — solo confirma que el edge no depende exclusivamente del stop apretado.

Reporte: `user_data/validation_reports/screen/XSecMomentum/20260711_100039/screen_report.json`

**Lectura crítica (13-E):** el PASA es válido pero el +252k no es motivo de celebración automática — ver diagnóstico siguiente.

---

## Diagnóstico 13-E — m35 sospechosamente bueno (2026-07-11)

**Pregunta:** ¿el 26× de Freqtrade es mecánica real o artefacto? ¿ZEC es el nuevo DEXE?

### Instrumento vs Freqtrade m35

| Motor | Múltiplo | Notas |
|-------|----------|-------|
| Research log W-FRI (B) | 10.37× | Referencia optimista pre-13-D |
| **Fidelidad stop −35%** (`simulate_freqtrade_fidelity`) | **7.25×** | 9 stops, 241 rotaciones |
| Fidelidad −35% sin compound | 6.86× | Compound en sim solo **+1.06×** |
| **Freqtrade m35 (10-RS)** | **26.2×** | Zip `2026-07-11_10-01-04` |

**Gap invertido:** FT/fidelidad ≈ **3.6×** (opuesto al ~2× research>FT del 13-D con stop −10%). El instrumento **no** predice el 26× — misma pregunta que a la 20M, dirección contraria.

Aislar compound en el simulador **no cierra** el gap (~1.06×). Residual sin nombre completo: stake policy FT + rank merge + rally ZEC no replicado en panel.

### PnL por par (zip m35)

| Par | Trades | PnL USDT | % total | Duración med. |
|-----|--------|----------|---------|---------------|
| **ZEC/USDT** | 22 | **+152 298** | **60.4%** | 14.3 d |
| DEXE/USDT | 21 | +87 785 | 34.8% | 16.0 d |
| AAVE/USDT | 19 | +17 364 | 6.9% | — |
| …resto… | — | neto negativo agregado | — | — |

**ZEC + DEXE ≈ 95%** del PnL. ZEC es el nuevo ancla exótica (vigilancia PC2).

### ZEC por año

| Año | Trades ZEC | PnL ZEC | % del total ZEC |
|-----|------------|---------|-----------------|
| 2021–2024 | 11 | +8 047 | 5.3% |
| **2025** | **7** | **+137 469** | **90.3%** |
| 2026 | 4 | +6 782 | 4.5% |

El 70% del titular es **concentración temporal**: casi todo el cohete ZEC es el rally 2025, no reparto uniforme.

### Counterfactual ex-ZEC (aprox., sin reemplazo en slots)

| Métrica | Con ZEC (FT) | Ex-ZEC (aprox.) |
|---------|--------------|-----------------|
| Múltiplo | 26.2× | **~11.0×** |
| Net PnL | +252k | **+99.8k** |
| Max DD (aprox.) | 45.6% (screen) | **~51%** (< 60%) |

Perfil **sigue operable** ex-ZEC en esta aproximación; LOO screen (+77k bruto) coherente.

### Expectativa pre-registrada — validación full (WF)

**Concentración temporal esperada (no invalida sola):**
- Ventanas WF **sin** ZEC en rally → resultados **mediocres** (positivos modestos vs ventanas 2025).
- Ventanas **con** ZEC en top momentum → pueden llevar el agregado.

**No invalidaría si:**
- Mayoría de ventanas sin ZEC siguen bruto > 0 y DD < umbral full.
- El agregado no depende de 1–2 ventanas OOS únicamente.

**Sí invalidaría si:**
- Mayoría de ventanas OOS bruto ≤ 0 sin ZEC en cartera.
- Veredicto full = una sola ventana parabólica ZEC.

Artefacto: `research/output/diagnose_m35_13e_20260711.json`

---

## MeanRevBB al cierre fix #10 (2026-07-11 ~12:00 UTC+2)

| Campo | Valor |
|-------|-------|
| Lock | **LOCKED** — `run_id=20260709_162954`, pid **16944** (vivo) |
| Fase | WF ventana 0 — `strategy_MeanRevBB_2026-07-11_08-58-25.fthypt` **~91 MB**, **~248/300** epochs |
| Re-screen XSec | **En cola** — ejecutar tras transición ventana 0→1 (~2 h estimadas) |
| `report.json` | No |

**Aislamiento:** fix en `screen_strategy.py` + fixtures; sin tocar `MeanRevBB.py` ni hyperopt en curso.

---

## Veredicto

**#10 control:** **PASA (10-RS)** — config validación **m35**. Entra a validación **entendido**: 26× FT vs 7.25× fidelidad (gap invertido 3.6×); ZEC 60% PnL (90% en 2025). PASA no implica que el titular sea robusto sin leer WF.

**Siguiente hito:** `report.json` MeanRevBB — sin trabajo adicional hasta entonces.

---

## Aislamiento del run vivo

**Grep imports MeanRevBB.py:** `quant_core`, `_base`, `talib`, `freqtrade` — **no** importa `XSecMomentum`, `xsec_momentum_core`, ni `screen_strategy.py`. Editar esos archivos no afecta el hyperopt MeanRevBB en curso.
