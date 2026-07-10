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
| 6 | E1 — Autopsia RM: momentum top-1/top-2 (7/14/30d) en 5 pares bate equal-weight con fricción | BTC,ETH,BNB,SOL,XRP 1d | `research/xsec_lab.py` cartera rebalanceo W/M, versión B | Alguna combo bate equal-weight B; si ninguna → hipótesis muerta en universo estrecho | **PENDIENTE** | 2026-07-10 |
| 7 | E2 — Momentum cross-sectional universo ancho (~30 pares USDT, top-3/top-5) | ~30 spot USDT 1d, hist≥3a | Mismo motor, versión B vs EW y BTC B&H | top-N bate EW y BTC B&H en B; turnover no anula edge | **PENDIENTE** | 2026-07-10 |
| 8 | E3 — Reversión post-extremos ±2σ (retorno 1/3/7d) por régimen BTC | Universo ancho 1d | Event study pandas; régimen reimplementado en research | t-stat>2 vs incondicional en **ambas** mitades 2021-23 / 2024-26 | **PENDIENTE** | 2026-07-10 |
| 9 | E4 — Estacionalidad día-de-semana | Universo ancho 1d | Medias por weekday; split temporal fijo | t-stat>2 en **ambas** mitades o descartar | **PENDIENTE** | 2026-07-10 |

---

*Nuevas filas se añaden al final. No editar filas históricas salvo corregir errores factuales con nota en `research/results_*`.*
