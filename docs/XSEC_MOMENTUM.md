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

Criterios: `docs/screen_protocol.md` sección rotación (estándar + LOO bruto>0 + max DD < 60%).

Variantes: `user_data/fixtures/screen_variants/XSecMomentum.json`

| Variante | w | top_n | exit_rank_k |
|----------|---|-------|-------------|
| research_baseline | 14 | 3 | 4 |
| conservative | 30 | 2 | 4 |
| wide | 7 | 4 | 5 |

### Resultados

*(Pendiente — screen en curso; ver `user_data/validation_reports/screen/XSecMomentum/<run_id>/screen_report.json`)*

---

## MeanRevBB al cierre de implementación

| Campo | Valor |
|-------|-------|
| Lock | LOCKED (validación full activa) |
| Fase | WF ventana 0 (~48/300 epochs al iniciar screen) |
| `report.json` | No |

---

## Veredicto

*(Pendiente screen)*

Si **PASA:** entra en cola de validación full **detrás** de calibración MeanRevBB — no lanzar `run_validation` ahora.

Si **DESCARTADA:** autopsia Freqtrade vs `research/xsec_lab.py` mismo timerange antes de cerrar #10.

---

## Aislamiento del run vivo

**Grep imports MeanRevBB.py:** `quant_core`, `_base`, `talib`, `freqtrade` — **no** importa `XSecMomentum`, `xsec_momentum_core`, ni `screen_strategy.py`. Editar esos archivos no afecta el hyperopt MeanRevBB en curso.
