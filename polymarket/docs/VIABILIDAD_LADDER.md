# Informe de Viabilidad — Temperature Ladder (micro)

**UTC:** `2026-08-10T10:40:00.879228+00:00`  
**Wallet analizado:** `$3.4482` · cap efectivo `$3.2758` · session cap `$5.0`  
**Perfil:** `weather_ladder_definitive_real_v1` · press-only DNA · floors CLOB · hold-to-resolution  
**Modo:** simulación only (sin órdenes on-chain)

---

## 0) Decisión ejecutiva

### `RESEARCH_ONLY`

Evidencia insuficiente para aumentar capital real: n=11 (mín. 30 para hablar de depósito; mín. 50 para GO_MICRO), Wilson95_lower=0.7412 (hace falta ≥0.80). El Monte Carlo remuestrea los mismos takes — no es validación OOS independiente. Riesgo material de overfitting DNA a ruido de julio–agosto.

Checks: **6/12**

| Check | OK |
|-------|----|
| `n_ge_30_for_deposit_talk` | ❌ |
| `n_ge_50_for_go` | ❌ |
| `wilson95_ge_80` | ❌ |
| `mc_is_not_independent_validation` | ❌ |
| `overfit_risk_acknowledged` | ✅ |
| `engineering_gates_ready` | ✅ |
| `geoblock_ok_assumed_vps_es` | ✅ |
| `take_sizeable_at_wallet` | ✅ |
| `survives_one_miss_armed` | ❌ |
| `mc80_ruin_prob_lt_25pct` | ✅ |
| `mc80_median_pnl_positive` | ✅ |
| `live_book_has_dna_take_now` | ❌ |

### Recomendación operativa

RESEARCH_ONLY: la ingeniería está lista, la evidencia no. n=11 y Wilson~0.74 no justifican depósito nuevo ni GO. Seguir en sim/vigilante DNA-gated; acumular ≥30 takes (ideal ≥50) antes de plantear más capital. No forzar near-miss. No martingale.

**Caveat MC:** Las celdas MC (ruin%, median PnL a 4 decimales) NO validan el edge: bootstrapean la misma muestra DNA. Tratarlas como sensibilidad de bankroll, no como prueba de WR.

### Umbrales de evidencia (duros)

| Umbral | Requerido | Observado |
|--------|----------:|----------:|
| n para hablar de depósito | 30 | 11 |
| n para GO_MICRO | 50 | 11 |
| Wilson95 lower | 0.8 | 0.7412 |

---

## 1) Contexto DNA y muestra

- Takes DNA históricos (press-only WR80 filters): **11**
- Días: `2026-07-12, 2026-07-14, 2026-07-15, 2026-07-16, 2026-07-17, 2026-07-22, 2026-07-27, 2026-08-03, 2026-08-04, 2026-08-07, 2026-08-09`
- WR research puntual: **1.0** (wins=11/11)
- Wilson 95% lower: **0.7412**
- Lectura honesta: con n=11, WR puntual=100% **no** se distingue estadísticamente de un sistema ~74% (o peor).
- Riesgo overfitting: el DNA puede estar memorizando coincidencias de esa ventana climática, no un edge estable.

---

## 2) What-if: take DNA ahora con este saldo

**Ejecutable.** Notional sized ≈ `$3.0`  
Template: `hong-kong` `2026-07-17` basket=0.4245

| Path | Spent | PnL | Equity |
|------|------:|----:|-------:|
| `clean_win` | 3.0 | 2.0 | 5.4482 |
| `full_miss` | 3.0 | -3.0 | 0.4482 |
| `friction_base_if_win` | 2.85 | 1.6738 | 5.122 |
| `friction_base_if_miss` | 2.85 | -2.85 | 0.5982 |
| `friction_slip_2c_if_win` | 2.85 | 1.4682 | 4.9164 |
| `friction_slip_2c_if_miss` | 2.85 | -2.85 | 0.5982 |
| `friction_slip_3c_fee50_if_win` | 2.7135 | 1.1995 | 4.6477 |
| `friction_slip_3c_fee50_if_miss` | 2.7135 | -2.7135 | 0.7347 |
| `friction_hostile_if_win` | 2.424 | 1.2124 | 4.6606 |
| `friction_hostile_if_miss` | 2.424 | -2.424 | 1.0242 |

---

## 3) Adequacy de capital (misses hasta ruin)

| Balance | Notional 1er take | Misses hasta ruin | ¿Sigue armed tras 1 miss? | Equity tras 1 miss |
|--------:|------------------:|------------------:|:-------------------------:|-------------------:|
| 3.4482 | 3.2733 | 1 | no | 0.1749 |
| 5 | 4.7487 | 1 | no | 0.2513 |
| 10 | 4.9973 | 2 | sí | 5.0027 |
| 15 | 4.9973 | 3 | sí | 10.0027 |
| 25 | 4.9973 | 5 | sí | 20.0027 |
| 50 | 4.9973 | 10 | sí | 45.0027 |
| 100 | 4.9973 | 20 | sí | 95.0027 |

---

## 4) Monte Carlo (sensibilidad de bankroll — NO validación del edge)

Reps por celda: **1500**. Cada take histórico se sizea con floors; win→settle con fricción; miss→−notional.

**Importante:** este MC **remuestrea los mismos n takes DNA**. No es validación OOS independiente. Los 4 decimales (ruin%, median) miden sensibilidad de capital bajo un WR *asumido*, no demuestran ese WR. Tratar la tabla como stress de bankroll.

| Start | WR asumido | Friction | Ruin% | Median PnL | P05 PnL | Mean End | P(profit) |
|------:|-----------:|----------|------:|-----------:|--------:|---------:|----------:|
| 3.4482 | 0.75 | base | 0.2607 | 46.0895 | -3.2739 | 41.5021 | 0.6627 |
| 3.4482 | 0.75 | hostile | 0.3393 | 28.7288 | -3.2739 | 27.5274 | 0.6607 |
| 3.4482 | 0.8 | base | 0.1993 | 57.573 | -3.2739 | 50.1942 | 0.7493 |
| 3.4482 | 0.8 | hostile | 0.2507 | 37.4981 | -3.2739 | 33.9377 | 0.7493 |
| 3.4482 | 0.9 | base | 0.0727 | 75.8568 | -3.2739 | 69.4482 | 0.9113 |
| 3.4482 | 0.9 | hostile | 0.0887 | 51.0 | -3.2739 | 48.0667 | 0.9113 |
| 3.4482 | 1.0 | base | 0.0 | 82.4632 | 82.4632 | 85.9114 | 1.0 |
| 3.4482 | 1.0 | hostile | 0.0 | 57.134 | 57.134 | 60.5822 | 1.0 |
| 5.0 | 0.75 | base | 0.248 | 61.821 | -4.7472 | 58.2731 | 0.752 |
| 5.0 | 0.75 | hostile | 0.2793 | 40.2236 | -4.7472 | 38.9017 | 0.7193 |
| 5.0 | 0.8 | base | 0.186 | 76.5332 | -4.7472 | 68.7655 | 0.814 |
| 5.0 | 0.8 | hostile | 0.2253 | 50.57 | -4.7472 | 45.9602 | 0.7733 |
| 5.0 | 0.9 | base | 0.08 | 97.3242 | -4.7472 | 91.1361 | 0.92 |
| 5.0 | 0.9 | hostile | 0.0993 | 66.8005 | -4.7472 | 63.3843 | 0.9 |
| 5.0 | 1.0 | base | 0.0 | 108.0298 | 108.0298 | 113.0298 | 1.0 |
| 5.0 | 1.0 | hostile | 0.0 | 75.8659 | 75.8659 | 80.8659 | 1.0 |
| 10.0 | 0.75 | base | 0.0653 | 69.7827 | -9.7494 | 75.2508 | 0.934 |
| 10.0 | 0.75 | hostile | 0.062 | 45.1516 | -9.7494 | 52.3675 | 0.9193 |
| 10.0 | 0.8 | base | 0.0413 | 79.3756 | 18.2073 | 84.5742 | 0.9587 |
| 10.0 | 0.8 | hostile | 0.0433 | 52.351 | -7.9021 | 59.3647 | 0.9473 |
| 10.0 | 0.9 | base | 0.01 | 98.0252 | 59.3867 | 102.1599 | 0.99 |
| 10.0 | 0.9 | hostile | 0.0113 | 67.1725 | 38.4023 | 73.0889 | 0.9873 |
| 10.0 | 1.0 | base | 0.0 | 108.8264 | 108.8264 | 118.8264 | 1.0 |
| 10.0 | 1.0 | hostile | 0.0 | 76.462 | 76.462 | 86.462 | 1.0 |
| 25.0 | 0.75 | base | 0.0013 | 72.1431 | 22.4533 | 93.776 | 0.994 |
| 25.0 | 0.75 | hostile | 0.0013 | 46.1124 | 10.5253 | 69.6017 | 0.9807 |
| 25.0 | 0.8 | base | 0.0027 | 79.3756 | 34.4965 | 101.2867 | 0.9967 |
| 25.0 | 0.8 | hostile | 0.0027 | 52.1269 | 19.3043 | 75.5262 | 0.992 |
| 25.0 | 0.9 | base | 0.0 | 98.0252 | 61.6515 | 117.819 | 1.0 |
| 25.0 | 0.9 | hostile | 0.0 | 67.1725 | 39.4808 | 88.6982 | 1.0 |
| 25.0 | 1.0 | base | 0.0 | 108.8264 | 108.8264 | 133.8264 | 1.0 |
| 25.0 | 1.0 | hostile | 0.0 | 76.462 | 76.462 | 101.462 | 1.0 |
| 50.0 | 0.75 | base | 0.0 | 72.916 | 25.8367 | 120.4717 | 0.996 |
| 50.0 | 0.75 | hostile | 0.0 | 48.2501 | 12.121 | 95.7564 | 0.9853 |
| 50.0 | 0.8 | base | 0.0 | 80.5692 | 35.3416 | 126.4831 | 0.998 |
| 50.0 | 0.8 | hostile | 0.0 | 52.4625 | 19.3162 | 100.6422 | 0.9953 |
| 50.0 | 0.9 | base | 0.0 | 98.0252 | 61.6515 | 143.3205 | 1.0 |
| 50.0 | 0.9 | hostile | 0.0 | 67.1725 | 39.7472 | 114.0622 | 1.0 |
| 50.0 | 1.0 | base | 0.0 | 108.8264 | 108.8264 | 158.8264 | 1.0 |
| 50.0 | 1.0 | hostile | 0.0 | 76.462 | 76.462 | 126.462 | 1.0 |
| 100.0 | 0.75 | base | 0.0 | 72.656 | 26.7467 | 169.9533 | 0.9967 |
| 100.0 | 0.75 | hostile | 0.0 | 47.5525 | 12.534 | 145.4067 | 0.9833 |
| 100.0 | 0.8 | base | 0.0 | 79.6594 | 34.1869 | 176.9721 | 0.9987 |
| 100.0 | 0.8 | hostile | 0.0 | 52.351 | 19.3043 | 151.0372 | 0.9947 |
| 100.0 | 0.9 | base | 0.0 | 98.0252 | 58.2433 | 192.537 | 1.0 |
| 100.0 | 0.9 | hostile | 0.0 | 67.1725 | 36.677 | 163.4303 | 1.0 |
| 100.0 | 1.0 | base | 0.0 | 108.8264 | 108.8264 | 208.8264 | 1.0 |
| 100.0 | 1.0 | hostile | 0.0 | 76.462 | 76.462 | 176.462 | 1.0 |

### Lectura MC @ wallet actual (WR=0.80, base)

- Ruin prob: **0.1993**
- Median PnL: **57.573** · P05: **-3.2739**
- Mean end equity: **50.1942**

### Comparativa @ $25 (WR=0.80, base)

- Ruin prob: **0.0027**
- Median PnL: **79.3756**

---

## 5) Replay determinista + loss stress

### Deposit × friction (hereda outcomes research; optimista si WR puntual=100%)

| Start | Scenario | Exec | WR | PnL | End | Skip floor | Skip cash |
|------:|----------|-----:|---:|----:|----:|-----------:|----------:|
| 3.4482 | base | 9/11 | 1.0 | 82.4632 | 85.9114 | 2 | 0 |
| 3.4482 | slip_2c | 9/11 | 1.0 | 68.2196 | 71.6678 | 2 | 0 |
| 3.4482 | slip_3c_fee50 | 9/11 | 1.0 | 54.409 | 57.8572 | 2 | 0 |
| 3.4482 | hostile | 9/11 | 1.0 | 57.134 | 60.5822 | 2 | 0 |
| 5.0 | base | 11/11 | 1.0 | 108.0298 | 113.0298 | 0 | 0 |
| 5.0 | slip_2c | 11/11 | 1.0 | 90.5728 | 95.5728 | 0 | 0 |
| 5.0 | slip_3c_fee50 | 11/11 | 1.0 | 72.9836 | 77.9836 | 0 | 0 |
| 5.0 | hostile | 11/11 | 1.0 | 75.8659 | 80.8659 | 0 | 0 |
| 10.0 | base | 11/11 | 1.0 | 108.8264 | 118.8264 | 0 | 0 |
| 10.0 | slip_2c | 11/11 | 1.0 | 91.283 | 101.283 | 0 | 0 |
| 10.0 | slip_3c_fee50 | 11/11 | 1.0 | 73.5861 | 83.5861 | 0 | 0 |
| 10.0 | hostile | 11/11 | 1.0 | 76.462 | 86.462 | 0 | 0 |
| 15.0 | base | 11/11 | 1.0 | 108.8264 | 123.8264 | 0 | 0 |
| 15.0 | slip_2c | 11/11 | 1.0 | 91.283 | 106.283 | 0 | 0 |
| 15.0 | slip_3c_fee50 | 11/11 | 1.0 | 73.5861 | 88.5861 | 0 | 0 |
| 15.0 | hostile | 11/11 | 1.0 | 76.462 | 91.462 | 0 | 0 |
| 25.0 | base | 11/11 | 1.0 | 108.8264 | 133.8264 | 0 | 0 |
| 25.0 | slip_2c | 11/11 | 1.0 | 91.283 | 116.283 | 0 | 0 |
| 25.0 | slip_3c_fee50 | 11/11 | 1.0 | 73.5861 | 98.5861 | 0 | 0 |
| 25.0 | hostile | 11/11 | 1.0 | 76.462 | 101.462 | 0 | 0 |
| 50.0 | base | 11/11 | 1.0 | 108.8264 | 158.8264 | 0 | 0 |
| 50.0 | slip_2c | 11/11 | 1.0 | 91.283 | 141.283 | 0 | 0 |
| 50.0 | slip_3c_fee50 | 11/11 | 1.0 | 73.5861 | 123.5861 | 0 | 0 |
| 50.0 | hostile | 11/11 | 1.0 | 76.462 | 126.462 | 0 | 0 |
| 100.0 | base | 11/11 | 1.0 | 108.8264 | 208.8264 | 0 | 0 |
| 100.0 | slip_2c | 11/11 | 1.0 | 91.283 | 191.283 | 0 | 0 |
| 100.0 | slip_3c_fee50 | 11/11 | 1.0 | 73.5861 | 173.5861 | 0 | 0 |
| 100.0 | hostile | 11/11 | 1.0 | 76.462 | 176.462 | 0 | 0 |

### Forced-miss paths

- **first_exec_miss**: end `$0.1743` · pnl `-3.2739` · ruined=`True` · forced_idx=`[0]`
- **first_two_exec_miss**: end `$0.1743` · pnl `-3.2739` · ruined=`True` · forced_idx=`[0, 1]`
- **first_exec_miss_at_10**: end `$103.2517` · pnl `93.2517` · ruined=`False` · forced_idx=`[0]`
- **first_exec_miss_at_25**: end `$119.1537` · pnl `94.1537` · ruined=`False` · forced_idx=`[0]`
- **two_miss_at_25**: end `$103.6934` · pnl `78.6934` · ruined=`False` · forced_idx=`[0, 1]`
- **mid_miss_idx3_at_wallet**: end `$61.0212` · pnl `57.573` · ruined=`False` · forced_idx=`[3]`

---

## 6) Cadencia e ingreso esperado (orientativo)

- WR=0.75: ~2.5/semana → wins≈1.875 · losses≈0.625 (Cadencia research histórica; no calendario fijo. Muchos días sin take.)
- WR=0.8: ~2.5/semana → wins≈2.0 · losses≈0.5 (Cadencia research histórica; no calendario fijo. Muchos días sin take.)
- WR=0.9: ~2.5/semana → wins≈2.25 · losses≈0.25 (Cadencia research histórica; no calendario fijo. Muchos días sin take.)

Con wallet micro, el PnL/$ por take win sized ~$3 es modesto (~+$1.2 a +$2 según fricción); el edge se escala con **más depósito en el mismo DNA**, no aflojando baskets.

---

## 7) Libro vivo

_Error: `Server error '503 Service Unavailable' for url 'https://api.open-meteo.com/v1/forecast?latitude=31.1443&longitude=121.8083&daily=temperature_2m_max&timezone=Asia%2FShanghai&forecast_days=3&models=ecmwf_ifs025'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/503`_

---

## 8) Riesgos y límites del informe

1. **n pequeño:** n=11; Wilson95 lower ~0.74. No vender certeza 95%>80%.
2. **MC ≠ validación:** bootstrap sobre los mismos takes; ilusión de precisión ≠ evidencia.
3. **Overfitting DNA:** filtros press-only pueden memorizar ruido de esas fechas.
4. **Depósito nuevo:** no justificado por este informe hasta n≥30 y Wilson≥0.80 (y GO solo con n≥50).
5. No es fill on-chain; FAK parcial / gap de libro pueden empeorar el miss.
6. Geoblock / keys / SAFE gates deben seguir OK en VPS ES.
7. Near-miss ricos **no** son edge; forzarlos rompe la disciplina.
8. Hold-to-resolution: capital locked hasta settle.

---

## 9) Plan RESEARCH_ONLY (postura actual)

1. **No** depositar capital adicional solo por este informe.
2. Seguir en sim / paper / vigilante DNA-gated; acumular takes hasta n≥30 (ideal ≥50).
3. Recalcular Wilson95 lower en cada nuevo take DNA; no usar WR puntual.
4. Mantener SAFE (`DRY_RUN` según política) hasta evidencia + capital runway.
5. Auto-execute solo si DNA estricto y el operador arma explícitamente tras umbrales.
6. Tras cualquier miss: no martingale ni aflojar gates.
7. Telegram: EDGE / EJECUCIÓN / FIN — sin spam de near-miss.

_Generado por `ladder_viability_report` · 2026-08-10T10:40:00.879228+00:00_
