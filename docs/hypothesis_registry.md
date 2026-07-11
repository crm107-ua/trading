# Registro de hipótesis (append-only)

**Regla:** el contador `#` **nunca se resetea**. Cada fila es un intento registrado **antes** de ejecutar la prueba. Si un resultado pasa un criterio, el reporte debe citar el número de intento acumulado (p. ej. «pasa siendo el intento #12»). A más intentos acumulados, más escrutinio y más exigencia de out-of-sample antes de creerlo — corrección informal por multiplicidad.

**Leyenda de resultado:** `DESCARTADA` | `VIVA (research)` | `VIVA (implementar)` | `INCONCLUSO` | `PENDIENTE`

| # | Hipótesis | Universo | Método de prueba | Criterio pre-fijado | Resultado | Fecha |
|---|-----------|----------|------------------|---------------------|-----------|-------|
| 1 | Trend following (TrendRider): trend 1h con filtros ADX/EMA/volumen genera edge bruto | 5 pares, 1h, 2021→2026 | Screen pre-validación Freqtrade (defaults + variantes) | ≥1 variante: bruto>0, trades≥30, comisiones<50% bruto | **DESCARTADA** — ningún bruto>0 | 2026-07-10 |
| 2 | Breakout volumen (BreakoutVol): rupturas Donchian + volumen | 5 pares, 1h, 2021→2026 | Screen Freqtrade | Igual screen_protocol | **DESCARTADA** — ningún bruto>0 | 2026-07-10 |
| 3 | Regime switcher: rama trend + rama range según régimen BTC | 5 pares, 1h, 2021→2026 | Screen Freqtrade | Igual screen_protocol | **DESCARTADA** — ningún bruto>0 | 2026-07-10 |
| 4 | Grid DCA en pullbacks (GridDCA): capas RSI + DCA | 5 pares, 1h, 2021→2026 | Screen Freqtrade | Igual screen_protocol | **DESCARTADA** — ningún bruto>0 | 2026-07-10 |
| 5 | Momentum cross-sectional 1d/1h (RelativeMomentum): top-N rotación | 5 mega-líquidos, 1h+1d, 2021→2026 | Screen Freqtrade | Igual screen_protocol | **DESCARTADA** — bruto ~−10k, params verificados | 2026-07-10 |
| 6 | E1 — Autopsia RM: momentum top-1/top-2 (7/14/30d) en 5 pares bate equal-weight con fricción | BTC,ETH,BNB,SOL,XRP 1d | `research/xsec_lab.py` cartera rebalanceo W/M, versión B (fee 0.1%/turnover) | Alguna combo bate equal-weight B; si ninguna → muerta en universo estrecho | **VIVA (implementación)** — best top-1 w14 W: final_B=46.6 vs EW 8.5 vs BTC 2.2 (intent #6) | 2026-07-10 |
| 7 | E2 — Momentum cross-sectional universo ancho (~30 pares USDT, top-3/top-5) | 16 pares 1d con hist≥2022 (de 34 descargados) | Mismo motor, versión B vs EW y BTC B&H | top-N bate EW y BTC B&H en B; turnover no anula edge | **INTERESANTE** — top-3 w14 W: final_B=10.4 vs EW 2.5 vs BTC 2.2 (intent #7) | 2026-07-10 |
| 8 | E3 — Reversión post-extremos ±2σ (retorno 1/3/7d) | 16 pares 1d | Event study pandas; split 2021-23 / 2024-26 | t-stat>2 vs incondicional en **ambas** mitades | **DESCARTADA** — 9 filas \|t\|>2 pero 0 estables en ambas mitades (intent #8) | 2026-07-10 |
| 9 | E4 — Estacionalidad día-de-semana | 16 pares 1d | Medias por weekday; split fijo | t-stat>2 en **ambas** mitades o descartar | **DESCARTADA** — 2 filas \|t\|>2, 0 estables (intent #9) | 2026-07-10 |
| 10 | XSecMomentum P1: rotación 1d top-3 w14 rebalanceo lunes, universo E2, filtro BEAR | 16 pares 1d | Screen Freqtrade + `--bias-controls` (LOO + max DD<60%) | screen_protocol rotación + controles sesgo research | **PASA confirmado (screen)** — fees auditadas (16% fricción real); research_baseline + wide; conservative falla DD/LOO (intent #10) | 2026-07-10 |
| 10-R0 | **Control de #10 (no es intento nuevo):** el efecto E2 sobrevive excluyendo DEXE y ZEC simultáneamente (los dos sospechosos de iliquidez) | 14 pares 1d (E2 sin DEXE/ZEC) | `xsec_lab` top-3 w14 W, versión B, datadir local PC | Wealth B > equal-weight del universo reducido **Y** wealth B > 2× — umbral fijado antes de calcular | **PASA** — B 3.81× vs EW 1.95× vs umbral 2×; pero mitad 2024-26 débil (B 1.13× < BTC 1.45×) — ver `r0_exdexe_exzec.json` | 2026-07-11 |
| 11 | Funding extremo = sobrecalentamiento: funding perp > p90 rolling 90d del par → retornos spot forward 1/3/7d peores que incondicionales | Universo E2 con perp USDT en Binance, funding 8h→diario | Event study pandas condicionado a funding alto; split 2021-23 / 2024-26 | t-stat > 2 (retorno condicionado < incondicional) en **ambas** mitades, por agregado; percentil 90 fijo, sin optimizar | **DESCARTADA** — signo CONTRARIO: t agregados +0.97…+5.97 (funding alto → retornos MEJORES); veto hunde la cartera 12.3×→2.7× (intent #11) | 2026-07-11 |
| 12 | Funding negativo + momentum positivo = señal contraria favorable: top-3 momentum restringido a pares con funding ≤ 0 al rebalanceo mejora al top-3 libre | Universo E2 con perp, spot 1d | Cartera top-3 w14 W restringida vs libre, versión B, ambas mitades | Mejora Sharpe B en **ambas** mitades **Y** ≥60% de semanas con cartera completa (3 posiciones) | **DESCARTADA** — Sharpe mejora 21-23 (0.15→0.35) pero colapsa 24-26 (0.85→0.15); semanas completas 51% < 60% (intent #12) | 2026-07-11 |
| 13 | El edge E2 no depende de la cola ilíquida: momentum top-3 sobrevive filtrando por volumen medio 30d | E2 filtrado por volumen (3 umbrales fijos: 5M / 20M / 50M USDT/día — los tres se reportan, no se elige a posteriori) | Top-3 w14 W sobre universo filtrado, versión B vs EW filtrado y BTC B&H, ambas mitades | En el umbral 20M: B bate EW-filtrado **y** BTC en **ambas** mitades | **PASA** — 20M: 21-23 B 3.57 vs EW 1.75/BTC 1.44; 24-26 B 4.69 vs EW 0.91/BTC 1.45; full 15.6× (intent #13) | 2026-07-11 |
| 13-A | **Autopsia (no intento nuevo):** LOO ex-SOL en pandas 20M — ¿H-frágil? | E2−SOL, filtro 20M w14 W B | `xsec_lab` cartera 20M sin SOL vs EW filtrado sin SOL | Wealth 20M ex-SOL < EW ex-SOL → H-frágil confirmada | **H-frágil rechazada** — 20M ex-SOL 12.35× > EW 1.25×; +51% vs sin filtro ex-SOL | 2026-07-11 |
| 13-B | **Autopsia (no intento nuevo):** ablación mecánica Freqtrade en pandas | E2, 20M vs sin filtro | Slots→BEAR→stop−35%→liq.exit acumulativo | Paso que invierte beneficio 20M vs sin filtro | **Ningún paso invierte** — filtro sigue mejorando; slots comprimen múltiplo 15.6→7.0 | 2026-07-11 |
| 13-C | **Autopsia (no intento nuevo):** forense zips Freqtrade 20M vs control | Trades screen existentes | PnL por par, exit_reason, composición | Inversión explicada por DEXE/ZEC filtrados | **Composición** — control +26k DEXE; 20M dominado SOL; 1× liq.exit | 2026-07-11 |

---

## Pre-registro validación XSecMomentum (2026-07-11, antes de `report.json` MeanRevBB)

**Congelar antes de leer el veredicto del control.** No modifica código hoy; fija qué se valida y qué es control.

| Rol | Configuración | Detalle |
|-----|---------------|---------|
| **Primaria** | **XSecMomentum-20M** | Mismo motor #10 + filtro liquidez dinámico 20M. **Autopsia 2026-07-11: degradada** — implementación fiel (paridad 0) pero efecto invertido en Freqtrade por composición (DEXE filtrado). No validar. |
| **Control** | XSecMomentum E2 sin filtro | Screen PASA (#10). **Única config para validación full** post-MeanRevBB. |

**Por qué primaria y no variante secundaria:** #13 pasa en 20M con patrón monótono 5M→20M→50M (edge se fortalece al quitar iliquidez). R0 (#10-R0) pasa el criterio global pero 2024-26 sin DEXE/ZEC queda en 1.13×; con filtro 20M la misma mitad da **4.69×** — la variante 20M resuelve el asterisco de R0 mejor que el universo original.

**Implementación Freqtrade (cuando toque, post-calibración):** el filtro debe evaluarse **en cada lunes de rebalanceo** con ventana 30d hasta la vela anterior; prohibido sustituir por universo estático precomputado (cambiaría la hipótesis).

---

## Observaciones bloqueadas (no explotar sin pre-registro nuevo)

| ID | Observación | Candado |
|----|-------------|---------|
| OBS-11a | En #11 el signo salió **invertido**: funding > p90 rolling 90d precede retornos spot forward **mejores** (t agregado hasta +5.97 en 2024-26). Tentador como señal de continuación. | **Hipótesis post-hoc** (signo volteado tras ver datos). Máximo descuento por multiplicidad. Si algún día se prueba → **intento nuevo** con criterio OOS estricto pre-fijado **antes** de correr. **Hoy no.** |

---

*Nuevas filas se añaden al final. No editar filas históricas salvo corregir errores factuales con nota en `research/results_*`.*
