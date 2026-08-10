# Simulación con cases reales — mejora de estrategia (PAPER)

**UTC:** `2026-08-10T13:24:57.948161+00:00`
**Cases:** 136
**Grid paper evaluado:** 5
**IS days / OOS days:** 16 / 16

> Simulación + fricción sobre cases reales. **No** es permiso de depósito ni cambio de DNA live.

## LIVE DNA (press-only, producción)
- takes n=11 WR=1.0 Wilson=0.7412
- pnl paper units=659.41
- bankroll $25 base: {'start': 25.0, 'scenario': 'base', 'n': 11, 'wr': 1.0, 'pnl': 437.407, 'end': 462.407, 'mult': 18.4963, 'dd': 0.0, 'pf': 10.0}
- bankroll $100 base: {'start': 100.0, 'scenario': 'base', 'n': 11, 'wr': 1.0, 'pnl': 627.9337, 'end': 727.9337, 'mult': 7.2793, 'dd': 0.0, 'pf': 10.0}
- bankroll $100 hostile: {'start': 100.0, 'scenario': 'hostile', 'n': 11, 'wr': 0.9091, 'pnl': 438.4516, 'end': 538.4516, 'mult': 5.3845, 'dd': 0.0009, 'pf': 1149.3803}
- income_gate_passed=True verdict=INCOME_GENERATION_ASSURED

## Champion operacional (= LIVE DNA)
- mode=`live_dna_press`
- takes n=11 WR=1.0 Wilson=0.7412
- pnl paper units=659.41
- $25 base: {'start': 25.0, 'scenario': 'base', 'n': 11, 'wr': 1.0, 'pnl': 437.407, 'end': 462.407, 'mult': 18.4963, 'dd': 0.0, 'pf': 10.0}
- $100 base: {'start': 100.0, 'scenario': 'base', 'n': 11, 'wr': 1.0, 'pnl': 627.9337, 'end': 727.9337, 'mult': 7.2793, 'dd': 0.0, 'pf': 10.0}
- $100 hostile: {'start': 100.0, 'scenario': 'hostile', 'n': 11, 'wr': 0.9091, 'pnl': 438.4516, 'end': 538.4516, 'mult': 5.3845, 'dd': 0.0009, 'pf': 1149.3803}
- income_gate_passed=True verdict=INCOME_GENERATION_ASSURED
- OOS $100 base: {'start': 100.0, 'scenario': 'base', 'n': 5, 'wr': 1.0, 'pnl': 139.1366, 'end': 239.1366, 'mult': 2.3914, 'dd': 0.0, 'pf': 10.0}
- Robust eligible paper modes: 3
- Near-live eligible: 1

## Research PAPER champion (NO live)
- mode=`paper_basket_55_ud` takes={'n': 14, 'wins': 13, 'wr_point': 0.9286, 'wilson95_lower': 0.6853, 'pnl_sum_paper_units': 671.46}
- $100 base: {'start': 100.0, 'scenario': 'base', 'n': 12, 'wr': 1.0, 'pnl': 630.6807, 'end': 730.6807, 'mult': 7.3068, 'dd': 0.0, 'pf': 10.0}
- OOS base100: {'start': 100.0, 'scenario': 'base', 'n': 5, 'wr': 1.0, 'pnl': 139.1366, 'end': 239.1366, 'mult': 2.3914, 'dd': 0.0, 'pf': 10.0}

## Near-live PAPER (≤0.50 / UD / leg≤0.39, NO promote)
- mode=`paper_press_only_strict` takes={'n': 11, 'wins': 11, 'wr_point': 1.0, 'wilson95_lower': 0.7412, 'pnl_sum_paper_units': 659.41}
- $100 base: {'start': 100.0, 'scenario': 'base', 'n': 11, 'wr': 1.0, 'pnl': 627.9337, 'end': 727.9337, 'mult': 7.2793, 'dd': 0.0, 'pf': 10.0}

## Aggressive PAPER max-PnL (NO live)
- mode=`paper_press_select` takes={'n': 28, 'wins': 22, 'wr_point': 0.7857, 'wilson95_lower': 0.6046, 'pnl_sum_paper_units': 1078.29}
- $100 base: {'start': 100.0, 'scenario': 'base', 'n': 25, 'wr': 0.8, 'pnl': 1164.0266, 'end': 1264.0266, 'mult': 12.6403, 'dd': 0.0554, 'pf': 13.4146}
- OOS: {'start': 100.0, 'scenario': 'base', 'n': 11, 'wr': 0.8182, 'pnl': 303.3597, 'end': 403.3597, 'mult': 4.0336, 'dd': 0.1125, 'pf': 8.1266}

## Top 8 variantes (por ranking OOS+gate)
- `paper_basket_55_ud` n=14 WR=0.9286 base100_pnl=630.6807 hostile100_pnl=439.8429 oos_base100=139.1366 gate=True
- `paper_basket_52_ud` n=12 WR=1.0 base100_pnl=630.6807 hostile100_pnl=439.8429 oos_base100=139.1366 gate=True
- `live_dna_press` n=11 WR=1.0 base100_pnl=627.9337 hostile100_pnl=438.4516 oos_base100=139.1366 gate=True
- `paper_press_only_strict` n=11 WR=1.0 base100_pnl=627.9337 hostile100_pnl=438.4516 oos_base100=139.1366 gate=True
- `paper_press_select` n=28 WR=0.7857 base100_pnl=1164.0266 hostile100_pnl=794.4201 oos_base100=303.3597 gate=False
- `paper_no_ud_press` n=25 WR=0.8 base100_pnl=1164.0266 hostile100_pnl=794.4201 oos_base100=303.3597 gate=False

## Conclusión

LIVE DNA ya genera ganancias en sim ($100 base pnl=627.9337; OOS base100 pnl=139.1366 wr=1.0 n=5). Champion operacional=`live_dna_press` (DNA intacta). Mejor paper research=`paper_basket_55_ud` ($100 base pnl=630.6807, OOS pnl=139.1366 wr=1.0 n=5). Mejor near-live (≤0.50/UD/leg≤0.39)=`paper_press_only_strict` (base100 pnl=627.9337). Máximo PnL paper agresivo=`paper_press_select` (base100 pnl=1164.0266 wr=0.8 n_takes=28). Ninguna variante paper se promueve a live hasta n≥50 + Wilson≥0.80 + READY_TO_REARM. Seguir capturando forward DNA.

## Live posture

- DNA live sigue press-only ≤0.50 / leg≤0.39 / UD.
- Ganancias de esta sim **no** autorizan depósito hasta READY_TO_REARM.
- Óptimo **largo plazo** ≠ max PnL paper: ver `long_term_robustness --write-docs` y [`LONG_HORIZON_OPTIMAL.md`](LONG_HORIZON_OPTIMAL.md).
