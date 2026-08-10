# Informe de Viabilidad — Temperature Ladder (micro)

**UTC:** `2026-08-10T10:32:28.614511+00:00`  
**Wallet analizado:** `$3.4482` · cap efectivo `$3.2758` · session cap `$5.0`  
**Perfil:** `weather_ladder_definitive_real_v1` · press-only DNA · floors CLOB · hold-to-resolution  
**Modo:** simulación only (sin órdenes on-chain)

---

## 0) Decisión ejecutiva

### `CONDITIONAL`

Take DNA cabe, pero 1 miss deja cash < $2 (no re-armar). Viable solo tras depositar ≥$25 o aceptar ruin risk del primer miss.

Checks: **6/8**

| Check | OK |
|-------|----|
| `dna_certified_research` | ✅ |
| `geoblock_ok_assumed_vps_es` | ✅ |
| `take_sizeable_at_wallet` | ✅ |
| `survives_one_miss_armed` | ❌ |
| `mc80_ruin_prob_lt_25pct` | ✅ |
| `mc80_median_pnl_positive` | ✅ |
| `deposit_25_recommended_clear` | ✅ |
| `live_book_has_dna_take_now` | ❌ |

### Recomendación operativa

Viabilidad CONDICIONAL: el sistema técnico está listo (VPS ES + DNA + Telegram), pero el bankroll actual no sobrevive 1 miss. Depositar ≥$25 antes del primer take; mientras, WAIT DNA-gated sin forzar near-miss.

---

## 1) Contexto DNA y muestra

- Takes DNA históricos (press-only WR80 filters): **11**
- Días: `2026-07-12, 2026-07-14, 2026-07-15, 2026-07-16, 2026-07-17, 2026-07-22, 2026-07-27, 2026-08-03, 2026-08-04, 2026-08-07, 2026-08-09`
- WR research puntual: **1.0** (wins=11/11)
- Wilson 95% lower: **0.7412**
- Caveat: muestra pequeña; no afirmar CI>80% salvo que el lower bound lo soporte.

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

## 4) Monte Carlo (bootstrap WR × depósito × fricción)

Reps por celda: **2500**. Cada take histórico se sizea con floors; win→settle con fricción; miss→−notional.

| Start | WR | Friction | Ruin% | Median PnL | P05 PnL | Mean End | P(profit) |
|------:|---:|----------|------:|-----------:|--------:|---------:|----------:|
| 3.4482 | 0.75 | base | 0.2548 | 46.0895 | -3.2739 | 41.8174 | 0.6652 |
| 3.4482 | 0.75 | hostile | 0.336 | 28.9529 | -3.2739 | 27.7769 | 0.664 |
| 3.4482 | 0.8 | base | 0.1992 | 57.573 | -3.2739 | 50.0485 | 0.75 |
| 3.4482 | 0.8 | hostile | 0.2504 | 37.4981 | -3.2739 | 33.7706 | 0.7492 |
| 3.4482 | 0.9 | base | 0.0828 | 75.8568 | -3.2739 | 68.4714 | 0.9032 |
| 3.4482 | 0.9 | hostile | 0.0968 | 51.0 | -3.2739 | 47.3723 | 0.9032 |
| 3.4482 | 1.0 | base | 0.0 | 82.4632 | 82.4632 | 85.9114 | 1.0 |
| 3.4482 | 1.0 | hostile | 0.0 | 57.134 | 57.134 | 60.5822 | 1.0 |
| 5.0 | 0.75 | base | 0.2536 | 61.4552 | -4.7472 | 57.4776 | 0.7464 |
| 5.0 | 0.75 | hostile | 0.3008 | 38.7424 | -4.7472 | 37.6031 | 0.6968 |
| 5.0 | 0.8 | base | 0.1992 | 74.189 | -4.7472 | 67.5033 | 0.8008 |
| 5.0 | 0.8 | hostile | 0.2252 | 50.57 | -4.7472 | 45.9448 | 0.7732 |
| 5.0 | 0.9 | base | 0.0876 | 97.3242 | -4.7472 | 90.5883 | 0.9124 |
| 5.0 | 0.9 | hostile | 0.1056 | 66.8005 | -4.7472 | 62.8475 | 0.894 |
| 5.0 | 1.0 | base | 0.0 | 108.0298 | 108.0298 | 113.0298 | 1.0 |
| 5.0 | 1.0 | hostile | 0.0 | 75.8659 | 75.8659 | 80.8659 | 1.0 |
| 10.0 | 0.75 | base | 0.0736 | 69.6683 | -9.7494 | 74.6272 | 0.926 |
| 10.0 | 0.75 | hostile | 0.0668 | 45.0321 | -9.7494 | 52.0283 | 0.914 |
| 10.0 | 0.8 | base | 0.0432 | 79.3756 | 18.1117 | 84.2999 | 0.9568 |
| 10.0 | 0.8 | hostile | 0.0444 | 52.6866 | -7.9021 | 59.2475 | 0.946 |
| 10.0 | 0.9 | base | 0.01 | 98.0252 | 56.9924 | 102.0145 | 0.99 |
| 10.0 | 0.9 | hostile | 0.01 | 67.1725 | 36.2862 | 73.0851 | 0.9884 |
| 10.0 | 1.0 | base | 0.0 | 108.8264 | 108.8264 | 118.8264 | 1.0 |
| 10.0 | 1.0 | hostile | 0.0 | 76.462 | 76.462 | 86.462 | 1.0 |
| 25.0 | 0.75 | base | 0.0016 | 72.087 | 23.751 | 93.7629 | 0.9948 |
| 25.0 | 0.75 | hostile | 0.0008 | 45.9927 | 9.7884 | 69.3037 | 0.9788 |
| 25.0 | 0.8 | base | 0.0016 | 79.3756 | 32.8898 | 101.5081 | 0.9976 |
| 25.0 | 0.8 | hostile | 0.0016 | 52.1269 | 18.5485 | 75.6821 | 0.9932 |
| 25.0 | 0.9 | base | 0.0 | 98.0252 | 61.6515 | 118.1137 | 1.0 |
| 25.0 | 0.9 | hostile | 0.0 | 67.1725 | 39.4808 | 88.927 | 1.0 |
| 25.0 | 1.0 | base | 0.0 | 108.8264 | 108.8264 | 133.8264 | 1.0 |
| 25.0 | 1.0 | hostile | 0.0 | 76.462 | 76.462 | 101.462 | 1.0 |
| 50.0 | 0.75 | base | 0.0 | 72.4527 | 24.2391 | 119.5344 | 0.9952 |
| 50.0 | 0.75 | hostile | 0.0 | 46.8259 | 10.8706 | 95.0612 | 0.984 |
| 50.0 | 0.8 | base | 0.0 | 80.86 | 34.3513 | 126.792 | 0.9976 |
| 50.0 | 0.8 | hostile | 0.0 | 52.8404 | 19.3162 | 100.8793 | 0.9948 |
| 50.0 | 0.9 | base | 0.0 | 98.0252 | 61.6515 | 143.3353 | 1.0 |
| 50.0 | 0.9 | hostile | 0.0 | 67.1725 | 39.0728 | 114.0819 | 1.0 |
| 50.0 | 1.0 | base | 0.0 | 108.8264 | 108.8264 | 158.8264 | 1.0 |
| 50.0 | 1.0 | hostile | 0.0 | 76.462 | 76.462 | 126.462 | 1.0 |
| 100.0 | 0.75 | base | 0.0 | 72.656 | 25.7235 | 169.7214 | 0.9956 |
| 100.0 | 0.75 | hostile | 0.0 | 47.1194 | 11.285 | 145.203 | 0.9824 |
| 100.0 | 0.8 | base | 0.0 | 79.3756 | 33.669 | 176.4992 | 0.9988 |
| 100.0 | 0.8 | hostile | 0.0 | 52.1269 | 18.9264 | 150.6909 | 0.9948 |
| 100.0 | 0.9 | base | 0.0 | 98.0252 | 58.5579 | 192.6413 | 1.0 |
| 100.0 | 0.9 | hostile | 0.0 | 67.1725 | 38.0883 | 163.5047 | 0.9996 |
| 100.0 | 1.0 | base | 0.0 | 108.8264 | 108.8264 | 208.8264 | 1.0 |
| 100.0 | 1.0 | hostile | 0.0 | 76.462 | 76.462 | 176.462 | 1.0 |

### Lectura MC @ wallet actual (WR=0.80, base)

- Ruin prob: **0.1992**
- Median PnL: **57.573** · P05: **-3.2739**
- Mean end equity: **50.0485**

### Comparativa @ $25 (WR=0.80, base)

- Ruin prob: **0.0016**
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

Open=8 · accepted_DNA=0 · near_miss=2
- `shanghai` basket=0.68 · `basket_cost=0.680>max=0.5+max_leg=0.410>0.39`
- `hong-kong` basket=0.57 · `basket_cost=0.570>max=0.5+ev=0.0080<0.01+not_underdispersed`

### Contrafactual (NO ejecutar)
- **shanghai** 0.68 → `REJECT — DNA gate` (EV$ approx if forced 1.1387)
- **hong-kong** 0.57 → `REJECT — DNA gate` (EV$ approx if forced 0.0421)

---

## 8) Riesgos y límites del informe

1. No es fill on-chain; FAK parcial / gap de libro pueden empeorar el miss.
2. n=11 research es pequeño; Wilson lower ~0.74 — no vender certeza 95%>80%.
3. Geoblock / keys / SAFE gates deben seguir OK en VPS ES.
4. Near-miss ricos **no** son edge; forzarlos rompe la certificación.
5. Hold-to-resolution: capital queda locked hasta settle del día.

---

## 9) Plan GO (si se acepta CONDITIONAL)

1. Depositar hasta **≥ $25 USDC** (ideal) antes del primer take.
2. Mantener `POLY_LIVE_DRY_RUN` según política hasta armar explícito.
3. Auto-execute solo DNA: basket≤0.50 + UD + leg≤0.39.
4. Tras 1 miss: revisar bankroll; no martingale ni aflojar gates.
5. Canal Telegram para EDGE / EJECUCIÓN / FIN.

_Generado por `ladder_viability_report` · 2026-08-10T10:32:28.614511+00:00_
