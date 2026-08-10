# Simulación con cases reales — mejora de estrategia (PAPER)

**UTC:** `2026-08-10T13:22:05.940923+00:00`
**Cases:** 136
**Grid paper evaluado:** 185
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
- Robust eligible paper modes: 78
- Near-live eligible: 11

## Research PAPER champion (NO live)
- mode=`grid:0.58_0.39_0_0_1.0_1.0` takes={'n': 22, 'wins': 17, 'wr_point': 0.7727, 'wilson95_lower': 0.5656, 'pnl_sum_paper_units': 767.63}
- $100 base: {'start': 100.0, 'scenario': 'base', 'n': 14, 'wr': 0.8571, 'pnl': 775.3064, 'end': 875.3064, 'mult': 8.7531, 'dd': 0.0949, 'pf': 18.3007}
- OOS base100: {'start': 100.0, 'scenario': 'base', 'n': 5, 'wr': 0.8, 'pnl': 220.744, 'end': 320.744, 'mult': 3.2074, 'dd': 0.063, 'pf': 11.4049}

## Near-live PAPER (≤0.50 / UD / leg≤0.39, NO promote)
- mode=`grid:0.50_0.36_1_1_1.0_1.0` takes={'n': 14, 'wins': 12, 'wr_point': 0.8571, 'wilson95_lower': 0.6006, 'pnl_sum_paper_units': 707.81}
- $100 base: {'start': 100.0, 'scenario': 'base', 'n': 14, 'wr': 0.8571, 'pnl': 775.3064, 'end': 875.3064, 'mult': 8.7531, 'dd': 0.0949, 'pf': 18.3007}

## Aggressive PAPER max-PnL (NO live)
- mode=`grid:0.52_0.36_0_0_0.5_1.0` takes={'n': 25, 'wins': 21, 'wr_point': 0.84, 'wilson95_lower': 0.6535, 'pnl_sum_paper_units': 1083.98}
- $100 base: {'start': 100.0, 'scenario': 'base', 'n': 25, 'wr': 0.84, 'pnl': 1172.0846, 'end': 1272.0846, 'mult': 12.7208, 'dd': 0.0495, 'pf': 14.2511}
- OOS: {'start': 100.0, 'scenario': 'base', 'n': 11, 'wr': 0.8182, 'pnl': 303.3597, 'end': 403.3597, 'mult': 4.0336, 'dd': 0.1125, 'pf': 8.1266}

## Top 8 variantes (por ranking OOS+gate)
- `grid:0.58_0.39_0_0_1.0_1.0` n=22 WR=0.7727 base100_pnl=775.3064 hostile100_pnl=517.0166 oos_base100=220.744 gate=True
- `grid:0.58_0.39_0_1_1.0_1.0` n=22 WR=0.7727 base100_pnl=775.3064 hostile100_pnl=517.0166 oos_base100=220.744 gate=True
- `grid:0.58_0.39_1_1_1.0_1.0` n=22 WR=0.7727 base100_pnl=775.3064 hostile100_pnl=517.0166 oos_base100=220.744 gate=True
- `grid:0.58_0.42_0_0_1.0_1.0` n=22 WR=0.7727 base100_pnl=775.3064 hostile100_pnl=517.0166 oos_base100=220.744 gate=True
- `grid:0.58_0.42_0_1_1.0_1.0` n=22 WR=0.7727 base100_pnl=775.3064 hostile100_pnl=517.0166 oos_base100=220.744 gate=True
- `grid:0.58_0.42_1_1_1.0_1.0` n=22 WR=0.7727 base100_pnl=775.3064 hostile100_pnl=517.0166 oos_base100=220.744 gate=True
- `grid:0.58_0.36_0_0_1.0_1.0` n=21 WR=0.7619 base100_pnl=775.3064 hostile100_pnl=517.0166 oos_base100=220.744 gate=True
- `grid:0.58_0.36_0_1_1.0_1.0` n=21 WR=0.7619 base100_pnl=775.3064 hostile100_pnl=517.0166 oos_base100=220.744 gate=True

## Conclusión

LIVE DNA ya genera ganancias en sim ($100 base pnl=627.9337; OOS base100 pnl=139.1366 wr=1.0 n=5). Champion operacional=`live_dna_press` (DNA intacta). Mejor paper research=`grid:0.58_0.39_0_0_1.0_1.0` ($100 base pnl=775.3064, OOS pnl=220.744 wr=0.8 n=5). Mejor near-live (≤0.50/UD/leg≤0.39)=`grid:0.50_0.36_1_1_1.0_1.0` (base100 pnl=775.3064). Máximo PnL paper agresivo=`grid:0.52_0.36_0_0_0.5_1.0` (base100 pnl=1172.0846 wr=0.84 n_takes=25). Ninguna variante paper se promueve a live hasta n≥50 + Wilson≥0.80 + READY_TO_REARM. Seguir capturando forward DNA.

## Live posture

- DNA live sigue press-only ≤0.50 / leg≤0.39 / UD.
- Ganancias de esta sim **no** autorizan depósito hasta READY_TO_REARM.
