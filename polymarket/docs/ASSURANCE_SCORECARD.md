# Assurance scorecard — Temperature Ladder

**UTC:** `2026-08-10T13:06:09.882952+00:00`
**Grade:** `A_ASSURED_OPS` (100.0%) — Grado de *preparación/assurance ops*, NO permiso de rearme. Rearme solo con READY_TO_REARM (evidencia+capital).

## Evidencia
- n=11 wins=11 WR=1.0 Wilson95=0.7412
- optimistic_to_deposit_talk=+19 takes
- perfect_1.00: additional_takes=39 reachable=True
- strong_0.90: additional_takes=39 reachable=True
- gate_min_0.85: additional_takes=173 reachable=True

## Atribución near-miss (no aflojar DNA)
- n=431 reasons={'basket_rich': 431, 'not_underdispersed': 243, 'max_leg': 123, 'ev_low': 82}
- waiting_gates={'basket': 285, 'ud': 171, 'leg': 61}
- gap min/p10/p50=0.04/0.04/0.16
- basket_rich domina → libros caros, no aflojar 0.50. UD frecuente en HK → modelos divergentes; esperar convergencia, no bypass.

## Libros cerca / UD stuck
- hong-kong 2026-08-11: best=0.54 gap=0.04 ud_min=2.688 stuck=True snaps=79
- hong-kong 2026-08-12: best=0.54 gap=0.04 ud_min=2.5 stuck=True snaps=79

## Capital what-if
- $3.4482: armed_after_1=False notional=3.2733 equity_after_1=0.1749
- $10: armed_after_1=True notional=4.9973 equity_after_1=5.0027
- $25: armed_after_1=True notional=4.9973 equity_after_1=20.0027
- $50: armed_after_1=True notional=4.9973 equity_after_1=45.0027
- $100: armed_after_1=True notional=4.9973 equity_after_1=95.0027

## Calidad snapshots
- n=632 recent_ud=1.0 recent_gates=1.0 ok=True

## Dual control
- passed=True runtime_refused=True checks={'requires_allow_rearm': True, 'checks_rearm_gate': True, 'starts_safe': True, 'requires_ready_status': True}

## Reglas pre-registradas
- {"dna_basket_max": 0.5, "dna_leg_max": 0.39, "dna_ud_ratio_max": 0.65, "min_n_go_micro": 50, "min_wilson_go": 0.8, "no_mc_as_evidence": true, "no_pre_july_synthetic_clob": true, "forward_snapshots_only_path_to_n": true, "rearm_requires_ready_gate": true, "note_es": "Reglas pre-registradas: no se pueden aflojar para 'asegurar' ingreso. Asegurar = más muestra forward + capital runway + controles duales."}

## Acción

Mantener WATCH_ONLY. Seguir capturando snapshots (calidad OK) y esperar resolve→cases. Wilson path: ver to_go_micro. Capital live insuficiente; $25 sim sí. UD stuck markets=2 — no bypass. Dual-control live refuse=OK. No depositar / no ALLOW_REARM hasta READY_TO_REARM.
