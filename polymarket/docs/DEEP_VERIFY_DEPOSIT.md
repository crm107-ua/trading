# Deep verify — depósito runway

**UTC:** `2026-08-10T14:13:12.462582+00:00`
**Veredicto:** `DEEP_VERIFY_DEPOSIT_RUNWAY_PASS` · score=13/13

Verificación profunda PASS para depositar $100–$200 en runway watch-only. Auto-execute sigue bloqueado por evidencia (n<50).

- can_deposit_runway_watch_only=`True`
- can_enable_auto_execute=`False` (siempre false aquí)

## Capas
- `A_safe` **PASS** (required)
- `B_dna_configs` **PASS** (required)
- `C_long_term` **PASS** (required)
- `D_income_mechanism` **PASS** (required)
- `E_capital_matrix` **PASS** (required)
- `F_deposit_runway` **PASS** (required)
- `G_sensitivity` **PASS** (required)
- `H_dna_structure` **PASS** (required)
- `J_dual_control` **PASS** (required)
- `L_rearm_consistency` **PASS** (required)
- `M_bootstrap_multimiss` **PASS** (required)
- `N_live_scripts_refuse` **PASS** (required)
- `K_forward_telemetry` **PASS** (optional)

## Highlights
- LT best=`income_wr80` verdict=`LONG_TERM_ROBUST` adversaries_fail=`True`
- DNA structure n=11 Wilson=0.7412 OOS=1.0
- Capital $100: {'deposit': 100.0, 'session_cap': 50.0, 'budget': 25.0, 'adequacy': {'executable': True, 'notional_first': 24.9969, 'equity_after_1_miss': 75.0031, 'still_armed_after_1_miss': True, 'misses_until_ruin': 4}, 'bankroll': {'base': {'n': 11, 'wr': 1.0, 'pnl': 627.9337, 'end': 727.9337, 'dd': 0.0, 'income_positive': True}, 'slip_3c_fee50': {'n': 11, 'wr': 0.9091, 'pnl': 429.5947, 'end': 529.5947, 'dd': 0.0026, 'income_positive': True}, 'hostile': {'n': 11, 'wr': 0.9091, 'pnl': 438.4516, 'end': 538.4516, 'dd': 0.0009, 'income_positive': True}}, 'passed': True}
- Deposit runway $100: {'status': 'DEPOSIT_RUNWAY_GO', 'can_deposit': True, 'can_auto': False, 'checks': {'engineering_ok': True, 'income_mechanism_ok': True, 'long_term_robust': True, 'planned_capital_survives_1_miss': True, 'planned_capital_executable': True, 'bankroll_base_positive': True, 'bankroll_hostile_positive': True, 'current_capital_blocks': True, 'evidence_n_ge_50': False, 'evidence_wilson_ge_80': False}, 'capital': {'balance': 100.0, 'notional_first': 24.9969, 'equity_after_1_miss': 75.0031, 'still_armed_after_1_miss': True, 'misses_until_ruin': 4}}
- Deposit runway $200: {'status': 'DEPOSIT_RUNWAY_GO', 'can_deposit': True, 'can_auto': False, 'capital': {'balance': 200.0, 'notional_first': 49.9976, 'equity_after_1_miss': 150.0024, 'still_armed_after_1_miss': True, 'misses_until_ruin': 4}}
- Rearm decision: {'status': 'DEPOSIT_RUNWAY_GO', 'blockers': ['evidence_n=11_wilson=0.7412_need_n>=50_wilson>=0.8', 'auto_execute_blocked_until_evidence'], 'action_es': 'PUEDES depositar $100.0 AHORA (runway, watch-only). NO armar auto-execute hasta n≥50 / Wilson≥0.80. El blocker de capital se resuelve con ese depósito; la evidencia sigue pendiente.', 'can_enable_auto_execute': False, 'can_recommend_deposit': True, 'can_deposit_runway_watch_only': True}

## Invariantes
- DNA press-only ≤0.50 / leg≤0.39 / UD no se relaja.
- Adversarios max-PnL deben fallar long-term gate.
- Deep verify PASS ≠ READY_TO_REARM / auto-execute.
