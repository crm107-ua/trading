# Deposit runway — verificación

**UTC:** `2026-08-10T13:40:49.361686+00:00`
**Status:** `DEPOSIT_RUNWAY_GO`
**Target:** `$200` (aggressive)

PUEDES depositar $200 AHORA para runway (watch-only). NO armar auto-execute: evidencia n=11 Wilson=0.7412 (falta n≥50, Wilson≥0.8). Tras depositar, primera sesión solo cuando READY_TO_REARM: budget $25 / cap $50.

## Flags
- can_deposit_runway_watch_only=`True`
- can_enable_auto_execute=`False`
- can_recommend_deposit (runway)=`True`

## Checks
- `engineering_ok`=True
- `income_mechanism_ok`=True
- `long_term_robust`=True
- `planned_capital_survives_1_miss`=True
- `planned_capital_executable`=True
- `bankroll_base_positive`=True
- `bankroll_hostile_positive`=True
- `current_capital_blocks`=True
- `evidence_n_ge_50`=False
- `evidence_wilson_ge_80`=False

## Capital planificado
- balance=$200.0 notional≈49.9976 after_1_miss=150.0024 still_armed=True misses_until_ruin=4

## Evidencia (auto-execute)
- n=11 Wilson=0.7412 rearm_ok=False

## Bankroll sim @ depósito
- base: {'n': 11, 'wr': 1.0, 'pnl': 1029.5652, 'end': 1229.5652, 'mult': 6.1478, 'dd': 0.0, 'income_positive': True}
- hostile: {'n': 11, 'wr': 0.9091, 'pnl': 719.5901, 'end': 919.5901, 'mult': 4.598, 'dd': 0.0009, 'income_positive': True}

Depositar runway ≠ auto-execute. DNA intacta. Tras depositar sigue WATCH_ONLY hasta READY_TO_REARM.
