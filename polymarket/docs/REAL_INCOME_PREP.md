# Verificación — preparación ingreso real

**UTC:** `2026-08-10T12:33:02.980432+00:00`
**Veredicto:** `SYSTEM_PREP_OK_EVIDENCE_BLOCK`

Ingeniería/SAFE/mecanismo OK. Mantener WATCH_ONLY. NO depositar ni armar: evidencia/capital bloquean rearme. Seguir capturando forward DNA hasta n≥50 y Wilson≥0.80 + capital ≥1 miss.

## Capas
- system_prep_ok=True
- mechanism_ok=True
- evidence_ready=False
- edge_open_now=False
- can_enable_auto_execute=False
- can_recommend_deposit=False

## SAFE / región
- passed=True · country=ES · mode=WATCH_ONLY
- checks={"armed_off": true, "dry_run_on": true, "signing_ready": true, "funder_present": true, "eoa_present": true, "geoblock_ok": true, "allow_rearm_unset": true, "real_confirm_unset": true, "watch_mode_file": true}

## Ingeniería / dry
- engineering_passed=True
- ladder_dry=LADDER_DRY_READY passed=True balance=3.4482

## Rearm gate
- status=NOT_READY
- blockers=['evidence_n=11_wilson=0.7412_need_n>=50_wilson>=0.8', 'capital_cannot_survive_1_miss']

## Forward evidencia
- n histórico=11 · Wilson=0.7412 · faltan GO_MICRO=39
- snapshots=352 · tracked=8 · dna_hits_fwd=0
- gates_2_of_3=[{'city': 'beijing', 'day': '2026-08-12', 'gates': 2, 'waiting': ['basket'], 'basket': 0.7}]
- close=[{'city': 'hong-kong', 'day': '2026-08-11', 'best_basket': 0.54, 'gap': 0.04}, {'city': 'hong-kong', 'day': '2026-08-12', 'best_basket': 0.54, 'gap': 0.04}]

## Capital what-if (sim)
- $3.4482: armed_after_1_miss=False notional=3.2733 equity_after_1=0.1749
- $25: armed_after_1_miss=True notional=4.9973 equity_after_1=20.0027
- $50: armed_after_1_miss=True notional=4.9973 equity_after_1=45.0027
- $100: armed_after_1_miss=True notional=4.9973 equity_after_1=95.0027

## Blockers
- `evidence_n=11_wilson=0.7412_need_n>=50_wilson>=0.8`
- `capital_cannot_survive_1_miss`

## Qué NO hacer ahora

- No `POLY_LADDER_ALLOW_REARM=1` hasta READY_TO_REARM.
- No depositar solo por MC / WR puntual con n pequeño.
- No aflojar DNA (basket 0.50 / leg 0.39 / UD).
- No sustituir watch por live manager.

## Qué sí está listo

- Path SAFE + scripts watch/live gated.
- Mecanismo de ingresos simulado con fricción.
- Watch forward acumulando snapshots → cases al resolver.

## Rearme (solo si READY_TO_REARM)

1. `python3 -m polymarket.research.local_lab.verify_real_income_prep` → READY.
2. Depositar solo si `can_recommend_deposit` (típicamente ≥$25 micro).
3. `POLY_LADDER_ALLOW_REARM=1` + PM2 `private_manager_live.sh`.
4. `POLY_LADDER_REAL_CONFIRM=1` ya lo pone el script live; accept-loss YES incluido.
5. Cap micro ≤$5/sesión; 1 miss → parar y revisar.
