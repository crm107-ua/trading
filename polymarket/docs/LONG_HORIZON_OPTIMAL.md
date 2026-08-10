# Óptimo a largo plazo (no PnL puntual)

**UTC:** `2026-08-10T13:24:47.416606+00:00`
**Universo:** 128 cases (2026-07-10 → 2026-08-10)

> Criterio: **robustez** (walk-forward, semanas, mitades, leave-one-city, sensibilidad, fricción). Maximizar PnL paper de una ventana **no** es óptimo.

## Champion durable
- profile=`income_wr80`
- overall n=11 WR=1.0 pnl=659.41
- walk-forward OOS WR=1.0 n=10
- verdict=`LONG_TERM_ROBUST` score=540.2
- config=`weather_ladder_final_longterm.json` (= DNA press-only ≤0.50 / leg≤0.39 / UD)

## Por qué no las variantes “más PnL”
- `punctual_basket58_no_ud` n=22 WR=0.7727 pnl=767.63 → `NOT_LONG_TERM_YET` fails=['overall_wr_ge_90', 'oos_walkforward_wr_ge_80', 'weekly_wr_ge_80_strict', 'both_halves_wr_ge_80', 'leave_one_city_ok']
- `punctual_basket52_leg36_no_ud` n=25 WR=0.84 pnl=1083.98 → `NOT_LONG_TERM_YET` fails=['overall_wr_ge_90', 'weekly_wr_ge_80_strict', 'both_halves_wr_ge_80', 'leave_one_city_ok']
- `punctual_select_core` n=25 WR=0.8 pnl=1079.9 → `NOT_LONG_TERM_YET` fails=['overall_wr_ge_90', 'oos_walkforward_wr_ge_80', 'weekly_wr_ge_80_strict', 'both_halves_wr_ge_80', 'friction_all_pass', 'leave_one_city_ok']

## Ranking perfiles durables
- `income_wr80` n=11 WR=1.0 OOS=1.0 score=540.2 verdict=LONG_TERM_ROBUST
- `press_ev03` n=11 WR=1.0 OOS=1.0 score=540.2 verdict=LONG_TERM_ROBUST
- `near_leg36` n=11 WR=1.0 OOS=1.0 score=540.2 verdict=LONG_TERM_ROBUST
- `press_bask48` n=9 WR=1.0 OOS=1.0 score=537.2 verdict=LONG_TERM_ROBUST
- `press_cons_lt` n=8 WR=1.0 OOS=1.0 score=534.7 verdict=LONG_TERM_ROBUST
- `press_no_hk` n=6 WR=1.0 OOS=1.0 score=528.6 verdict=LONG_TERM_ROBUST
- `press_post42` n=5 WR=1.0 OOS=1.0 score=479.5 verdict=NOT_LONG_TERM_YET
- `ssh_bj_tight` n=4 WR=1.0 OOS=1.0 score=-1000000000.0 verdict=NOT_LONG_TERM_YET
- `lt_core_final` n=4 WR=1.0 OOS=1.0 score=-1000000000.0 verdict=NOT_LONG_TERM_YET
- `lt_almost_perfect` n=4 WR=1.0 OOS=1.0 score=-1000000000.0 verdict=NOT_LONG_TERM_YET

## Regla operativa

1. Estrategia canónica largo plazo = `income_wr80` / DNA live (press-only + UD + BJ≤0.50).
2. Más ingreso durable = **más capital / más n forward**, no relajar basket/UD/select.
3. Re-certificar con `long_term_robustness` cuando suba n; no promover paper agresivo.
4. Depósito solo con `READY_TO_REARM` (n≥50, Wilson≥0.80).

Ver también: [`FINAL_LONGTERM_STRATEGY.md`](FINAL_LONGTERM_STRATEGY.md) · [`SIM_GAINS_REPORT.md`](SIM_GAINS_REPORT.md) (sim PnL ≠ óptimo LT).
