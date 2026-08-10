# Sim bankroll $100 / $200 (hipotético, sin real)

**UTC:** `2026-08-10T11:10:19.180846+00:00`
**DNA takes:** 11
**Session cap sim:** `$50.0` · budget/trade `$25.0`

Hipotético: mismo DNA, sizing con session_cap/budget altos para simular comportamiento con 100€/200€. No es permiso de GO ni rearme. n=11 sigue siendo evidencia débil — estas cifras son sensibilidad de bankroll.

## Adequacy (misses hasta ruin)

| Balance | Notional 1º | Misses hasta ruin | Armed tras 1 miss | Equity tras 1 miss |
|--------:|------------:|------------------:|:-----------------:|-------------------:|
| 100 | 24.9969 | 4 | sí | 75.0031 |
| 200 | 24.9969 | 8 | sí | 175.0031 |

## What-if take DNA ahora

### $100
- Notional sized: `$24.9969`

| Path | Spent | PnL | Equity |
|------|------:|----:|-------:|
| `clean_win` | 24.9969 | 99.6631 | 199.6631 |
| `full_miss` | 24.9969 | -24.9969 | 75.0031 |
| `friction_base_if_win` | 23.7471 | 82.8372 | 182.8372 |
| `friction_base_if_miss` | 23.7471 | -23.7471 | 76.2529 |
| `friction_slip_2c_if_win` | 23.7471 | 73.1478 | 173.1478 |
| `friction_slip_2c_if_miss` | 23.7471 | -23.7471 | 76.2529 |
| `friction_slip_3c_fee50_if_win` | 22.6097 | 61.5358 | 161.5358 |
| `friction_slip_3c_fee50_if_miss` | 22.6097 | -22.6097 | 77.3903 |
| `friction_hostile_if_win` | 20.1975 | 61.3981 | 161.3981 |
| `friction_hostile_if_miss` | 20.1975 | -20.1975 | 79.8025 |

### $200
- Notional sized: `$24.9969`

| Path | Spent | PnL | Equity |
|------|------:|----:|-------:|
| `clean_win` | 24.9969 | 99.6631 | 299.6631 |
| `full_miss` | 24.9969 | -24.9969 | 175.0031 |
| `friction_base_if_win` | 23.7471 | 82.8372 | 282.8372 |
| `friction_base_if_miss` | 23.7471 | -23.7471 | 176.2529 |
| `friction_slip_2c_if_win` | 23.7471 | 73.1478 | 273.1478 |
| `friction_slip_2c_if_miss` | 23.7471 | -23.7471 | 176.2529 |
| `friction_slip_3c_fee50_if_win` | 22.6097 | 61.5358 | 261.5358 |
| `friction_slip_3c_fee50_if_miss` | 22.6097 | -22.6097 | 177.3903 |
| `friction_hostile_if_win` | 20.1975 | 61.3981 | 261.3981 |
| `friction_hostile_if_miss` | 20.1975 | -20.1975 | 179.8025 |

## Replay histórico DNA (optimista si WR puntual=100%)

| Start | Scenario | Exec | WR | PnL | End |
|------:|----------|-----:|---:|----:|----:|
| 100.0 | base | 11/11 | 1.0 | 684.2966 | 784.2966 |
| 100.0 | hostile | 11/11 | 1.0 | 489.7119 | 589.7119 |
| 200.0 | base | 11/11 | 1.0 | 684.2966 | 884.2966 |
| 200.0 | hostile | 11/11 | 1.0 | 489.7119 | 689.7119 |

## Forced miss stress

- **100_first_miss**: end `$685.9222` · pnl `585.9222` · ruined=`False` · n_exec=`11`
- **100_two_miss**: end `$578.0881` · pnl `478.0881` · ruined=`False` · n_exec=`11`
- **200_first_miss**: end `$785.9222` · pnl `585.9222` · ruined=`False` · n_exec=`11`
- **200_two_miss**: end `$678.0881` · pnl `478.0881` · ruined=`False` · n_exec=`11`

## Monte Carlo (sensibilidad — NO validación OOS)

| Start | WR | Friction | Ruin% | Median PnL | P05 PnL | Mean End |
|------:|---:|----------|------:|-----------:|--------:|---------:|
| 100.0 | 0.75 | base | 0.006 | 453.469 | 191.4897 | 544.569 |
| 100.0 | 0.75 | hostile | 0.005 | 306.2484 | 106.2261 | 399.5395 |
| 100.0 | 0.8 | base | 0.002 | 503.7137 | 247.7383 | 591.8644 |
| 100.0 | 0.8 | hostile | 0.002 | 347.9111 | 149.131 | 436.6465 |
| 100.0 | 0.9 | base | 0.0 | 585.9222 | 393.5432 | 685.1947 |
| 100.0 | 0.9 | hostile | 0.0 | 409.9392 | 263.3435 | 510.5773 |
| 200.0 | 0.75 | base | 0.0 | 459.5122 | 202.0242 | 647.5331 |
| 200.0 | 0.75 | hostile | 0.0 | 306.2484 | 111.7343 | 500.9138 |
| 200.0 | 0.8 | base | 0.0 | 513.332 | 259.4314 | 694.1904 |
| 200.0 | 0.8 | hostile | 0.0 | 349.2725 | 160.7603 | 537.9627 |
| 200.0 | 0.9 | base | 0.0 | 592.5742 | 394.8776 | 785.0031 |
| 200.0 | 0.9 | hostile | 0.0 | 409.9392 | 268.3456 | 610.6807 |

## Lectura operativa

- Con $100/$200 el path **sí aguanta varios misses** (a diferencia de $3.45).
- El PnL hipotético escala con notional; el **edge DNA no está más demostrado**.
- Rearme real sigue bloqueado por evidencia (n=11) — esto solo ilustra bankroll.
