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
| 10 | XSecMomentum P1: rotación 1d top-3 w14 rebalanceo lunes, universo E2, filtro BEAR | 16 pares 1d | Screen Freqtrade + `--bias-controls` (LOO + max DD<60%) | screen_protocol rotación + controles sesgo research | **PENDIENTE** | 2026-07-10 |

---

*Nuevas filas se añaden al final. No editar filas históricas salvo corregir errores factuales con nota en `research/results_*`.*
