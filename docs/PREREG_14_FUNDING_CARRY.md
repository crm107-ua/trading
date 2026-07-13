# Pre-registro #14 — Funding Rate Carry (delta-neutral)

**Congelado:** 2026-07-13 — **antes de cualquier backtest, screen o lectura de resultados.**  
**Fase 0:** `docs/FUNDING_CARRY_FEASIBILITY.md` (GO condicionado).  
**Mecanismo (vinculante):** los longs apalancados en perpetuos pagan funding de forma sistemática; la estrategia cobra ese pago. Quién pierde: el especulador apalancado que paga por conveniencia de apalancamiento sin vencimiento.

---

## Decisiones congeladas (stakeholder + lab)

| Tema | Decisión | Notas |
|------|----------|-------|
| **Estructura** | **Delta-neutral spot long + short perp** | Descartado short perp direccional — confunde beta con carry (falso positivo/negativo por precio). |
| **Motor** | Simulador dual-leg en `research/` | **No** pipeline Freqtrade nativo. Mismo rigor de costes y criterios; **no** relajar por estar “fuera del pipeline”. |
| **Capital referencia** | **10 000 USDT** | Ver § Techo económico. |
| **Presupuesto** | **≤ 6 h/semana**, cierre **2026-08-31** | Sin veredicto GO-live → **archivar sin apelación** (igual que #10). |
| **Runs** | **Un solo** ciclo screen + WF + OOS | Sin iteraciones. Sin hyperopt sobre umbrales de señal. |

---

## Por qué delta-neutral y no direccional

| Estructura | Qué mide realmente | Veredicto |
|------------|-------------------|-----------|
| Short perp direccional | Funding **+** beta short (precio) | **Rechazada** — puede PASAR o MORIR por movimiento de mercado, no por carry. Optimiza la herramienta (pipeline Freqtrade), no la hipótesis. |
| Delta-neutral spot + short perp | Funding neto − fricción − basis drift | **Elegida** — aísla el mecanismo #14. |

El simulador **debe** modelar ambas patas con comisiones y slippage independientes. La neutralidad delta es **objetivo de diseño** (notional 1:1); el residual de basis se reporta explícitamente, no se oculta.

---

## Techo económico (10 000 USDT)

*Cálculo obligatorio antes de invertir más tiempo — acota el ROI del proyecto.*

| Supuesto | Valor |
|----------|-------|
| Carry bruto p90 (majors, fase 0) | ~18–23% anualizado **si** se estuviera short todo el tiempo en regímenes altos |
| Carry bruto **realista** (señal filtrada, no siempre en mercado) | Orden de magnitud **menor** que la media/p90 |
| Neto tras fricción ~0,50–0,70%/ciclo + permanencias imperfectas | **~5–10% anual** en escenario **bueno** (generoso) |
| USDT/año sobre 10k | **~500–1 000 USDT/año** |
| Equivalencia laboral (tarifa Upwork implícita) | **~15–30 h facturadas** en el escenario bueno |

**Implicación:** el presupuesto de 6 h/semana × ~7 semanas (~42 h) solo se justifica como **prueba de mecanismo**, no como negocio a escala 10k. Si el neto no supera fricción en papel, **muerte deseada** — no gastar máquina.

---

## Universo

### Regla dura (elegibilidad)

Perpetuo USDT en Binance con **≥ 4 años** de historial de funding al **2026-07-13** (primer `fundingTime` ≤ 2022-07-13).

*Motivo:* historial corto (DEXE desde 2024-12) es trampa de sobreajuste — lección del lab.

### Whitelist congelada (4 pares)

Solo estos activos entran en el **único** run de validación:

| Par | Primer funding | Años al corte | Rol |
|-----|----------------|---------------|-----|
| BTC/USDT | 2019-09-10 | ~6,8 | Anchor liquidez |
| ETH/USDT | 2019-11-27 | ~6,6 | Anchor liquidez |
| BNB/USDT | 2020-02-10 | ~6,4 | “Poco más” líquido |
| SOL/USDT | 2020-09-13 | ~5,8 | “Poco más” líquido |

**Excluidos explícitamente** (aunque cumplan ≥4 años): todo el resto de E2 (ADA, XRP, DOGE, ZEC, …) y cualquier par con listing tardío (DEXE, etc.). Ampliar universo = **intento nuevo**, no iteración de #14.

### Criterio de liquidez (objetivo, pre-fijado)

- Mediana volumen **spot** quote 30d ≥ **50 M USDT/día** al día de entrada (dato spot 1d del lab).
- Los 4 pares de la whitelist lo cumplen con margen; el filtro queda como **guardrail** documentado en el manifest del run.

---

## Señal (parámetros fijos — prohibido optimizar)

Granularidad de funding: **8 h** (3 periodos/día).  
Funding anualizado en el simulador: `rate_8h × 3 × 365`.

### Entrada (abrir delta-neutral)

Entrar en un par **solo si**:

1. Funding anualizado **> 12%** durante **3 periodos consecutivos** de 8 h (24 h).

**Justificación económica (no data-mining):**

- La media de largo plazo en BTC/ETH (~11% anualizado con permanencia total, fase 0) es el “impuesto normal” de crowding long.
- **12%** exige crowding **por encima de lo normal**, sin restringir solo al tail p90 (que sería ~18–23% y casi nunca operaría).
- **3 periodos** exige persistencia 24 h — descarta spikes de una sola liquidación de funding.

### Salida (cerrar ambas patas)

Cerrar posición en un par si **cualquiera**:

1. Funding anualizado **< 6%** en el periodo de 8 h actual, **o**
2. **21 días calendario** en posición (máximo).

**Justificación:**

- **6%** anualizado está por debajo del carry “normal” y del umbral de entrada — si el mercado deja de pagar prima, no tiene sentido pagar fricción de mantenimiento.
- **21 días** evita permanencias infinitas que diluyen el coste de oportunidad del capital y acumulan basis drift sin señal renovada.

### Asignación de capital

- Máximo **2 posiciones** simultáneas.
- Si varios pares califican: prioridad por **mayor funding anualizado** en el periodo de señal.
- Notional por posición: **50%** del capital desplegable cada una (10k → hasta 5k notional por pierna por slot, 2 slots).
- Sin apalancamiento adicional (perp 1× para neutralizar delta con spot).

---

## Estructura operativa (simulador dual-leg)

Por cada posición abierta:

| Pata | Acción | Notional |
|------|--------|----------|
| Spot | Long | `N` USDT |
| Perp USDT-M | Short | `N` USDT (1×) |

**PnL atribuido al mecanismo:**

- **+** funding cobrado en short (cada 8 h, tasa del API).
- **−** comisiones y slippage en las 4 ejecuciones por ciclo (abrir spot, abrir perp, cerrar spot, cerrar perp).
- **±** basis drift (mark − spot) reportado por separado — no confundir con carry.

**Rebalanceo / sincronización:** evaluación cada cierre de vela de funding (8 h). Spot ejecuta al **close spot 1h** alineado al timestamp de funding (misma convención que `research/download_funding_local.py`).

---

## Costes modelados (idéntico rigor que Freqtrade / #13-F)

| Concepto | Valor fijo | Fuente |
|----------|------------|--------|
| Comisión spot | **0,10%** / lado | Binance VIP0 taker; `base.json` fee 0.001 |
| Comisión perp | **0,05%** / lado | Binance USDⓈ-M VIP0 taker |
| Slippage spot | **0,10%** / lado | Majors líquidos; conservador vs 0,56% (#13-F iliquido) |
| Slippage perp | **0,10%** / lado | Idem |
| **Fricción total por ciclo completo** | **~0,70%** del notional | 0,30% fees + 0,40% slippage (4 ejecuciones) |

Prohibido reducir slippage post-hoc salvo intento nuevo documentado.

**Versión de costes:** “B” del lab (explícita, auditable en JSON de salida).

---

## Protocolo de validación (un solo run)

**Artefacto principal:** `research/output/funding_carry_14/<run_id>/report.json`  
**Script (a implementar post-prereg):** `research/funding_carry_lab.py`  
**Datos:** `research/data_local/funding/` + `research/data_local/binance/` (spot 1h/1d según necesidad de ejecución).

### A) Screen (research)

Ventana: **2021-01-01 → último dato disponible** (misma cultura temporal que E2).

**PASA screen** solo si **todas**:

| # | Criterio |
|---|----------|
| 1 | PnL **neto** (carry + basis − fricción) **> 0** en ventana completa |
| 2 | **Carry neto cobrado > costes totales de fricción** (suma fees+slippage) |
| 3 | **≥ 20 ciclos** de posición completos (equivalente trades) |
| 4 | Mitad **2021-23** y mitad **2024-26**: PnL neto **> 0** en **ambas** |
| 5 | Max drawdown **< 30%** (carry delta-neutral no debería comportarse como momentum; DD alto indica basis/fallo de sim) |

Si falla cualquiera → **DESCARTADA** en screen; **no** hay validación WF/OOS.

### B) Walk-forward (sin hyperopt)

Espejo del espíritu `docs/VALIDATION.md`:

| Parámetro | Valor |
|-----------|-------|
| Ventanas | **15** |
| Train | **12 meses** |
| Test | **3 meses** |
| Parámetros de señal | **Fijos** (tabla § Señal) — **cero** hyperopt |
| WFE mínimo | **≥ 0,50** (misma constante congelada `DEFAULT_WALK_FORWARD_EFFICIENCY_MIN`) |

WFE = métrica estándar del lab sobre curva OOS cosida / referencia IS del motor (documentar fórmula exacta en el script; no inventar otra en post).

### C) OOS final

- Split fijo: **IS 2021-01-01 → 2023-12-31** / **OOS 2024-01-01 → fin de datos**.
- Sin reoptimizar nada en IS.

---

## Condiciones de muerte (pre-escritas, vinculantes)

Cualquiera dispara **MUERTA** — cerrar #14 en registry, sin apelación, sin segundo run:

| ID | Condición |
|----|-----------|
| D-1 | **Carry neto cobrado < costes totales de fricción** (ventana completa o en **ambas** mitades del screen) |
| D-2 | Sharpe **OOS** (2024-26) **< 0,50** |
| D-3 | **> 40%** del PnL neto atribuible a **un solo activo** (lección ZEC #13-E) |
| D-4 | WFE **< 0,50** |
| D-5 | Screen no PASA (tabla § A) |

**Veredicto GO-live** (solo si sobrevive todo): screen PASA + WF WFE ≥ 0,5 + OOS Sharpe ≥ 0,5 + D-1..D-3 negativos. Aun así, techo económico § puede llevar a **no desplegar** capital real — GO-live operativo es decisión humana posterior, no automática.

---

## Expectativa escrita de fallo

**Lo más probable:** #14 **muere en D-1 (costes)** — el carry neto no supera la fricción de ~0,70%/ciclo con permanencias realistas (entradas a 12% anualizado, salidas a 6%, max 21 días). La mediana de funding es inferior al p90; tras filtrar señal y pagar cuatro patas, el neto anual sobre 10k puede quedar **por debajo del coste de oportunidad del tiempo del proyecto**.

**Otros modos de muerte plausibles:**

- **D-3:** concentración en SOL o BNB en un subperiodo alcista (basis residual, no carry).
- **D-4:** inestabilidad temporal — carry funciona 2021-23 pero no 2024-26 (o viceversa) por cambio de microestructura del perp.

**Estaría bien que muriera en el papel** antes de gastar máquina. El screen research es barato; si D-1 falla ahí, **stop** — no implementar WF.

---

## Reglas del proyecto (reafirmadas)

1. **Prohibido** hyperopt o grid search sobre `12%`, `6%`, `3 periodos`, `21 días`, whitelist o umbrales de liquidez.
2. **Prohibido** mirar resultados parciales y editar este documento.
3. **Prohibido** usar short perp direccional “como aproximación” o puente hacia Freqtrade.
4. **Prohibido** ampliar universo más allá de la whitelist de 4 sin nuevo intento en registry.
5. Si **2026-08-31** no hay veredicto GO-live documentado → **archivar #14** sin apelación.
6. Un solo run. Si el simulador tiene bug material **antes** de emitir veredicto → fix + rerun cuenta como **mismo** intento solo si el bug se documenta en `docs/validation_incidents.md` **antes** de leer métricas; si ya se leyeron resultados, **intento nuevo** (no aplica a #14 salvo nuevo #).

---

## Secuencia de implementación (post-prereg, orden fijo)

1. `research/funding_carry_lab.py` — dual-leg, costes §, señal §, manifest de datos.
2. Descargar/verificar funding + spot para whitelist (manifest con fecha corte ≥4 años).
3. **Screen** → si MUERTA por D-1, **stop** (registrar en registry).
4. **WF 15×** (solo si screen PASA).
5. **OOS** + `report.json` + actualizar fila #14 en `docs/hypothesis_registry.md`.

**Presupuesto tiempo estimado:** implementación sim ~12–18 h + 1 run ~2–4 h + documentación ~2 h → cabe en 6 h/semana hasta 2026-08-31 si el screen mata pronto.

---

## Referencias

- `docs/FUNDING_CARRY_FEASIBILITY.md` — viabilidad técnica fase 0
- `docs/hypothesis_registry.md` — intento #14
- `docs/screen_protocol.md` — espíritu de gates (adaptado a research)
- `docs/calibration_protocol.md` — WFE 0,50, Sharpe OOS
- `research/download_funding_local.py` — fuente funding
- `research/output/stress_13f_20260713.json` — referencia slippage

---

*Documento congelado. Cualquier cambio numérico o de universo requiere nuevo número de intento en el registry.*
