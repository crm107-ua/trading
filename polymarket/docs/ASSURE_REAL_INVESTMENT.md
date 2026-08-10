> Fuente: batería completa en **VPS ES** (geo OK).

# Assure real investment — matriz exhaustiva

**UTC:** `2026-08-10T14:13:12.668985+00:00`
**Veredicto:** `ASSURE_REAL_INVESTMENT_DEPOSIT_RUNWAY_GO`

ASEGURADO para depositar $100 (o $200) como runway watch-only. El sistema funciona bajo la matriz exhaustiva de posibilidades operativas/capital/DNA. NO asegurado: profit forward ni auto-execute. Tu inversión real queda protegida por: SAFE posture + DNA fijo + miss runway + bloqueo de auto.

- can_deposit_runway_watch_only=`True`
- can_enable_auto_execute=`False`
- recommended_deposit=`$100` stretch=`$200`
- balance_now=`$3.4482`
- confidence: Alta confianza operativa/ingenieril para runway watch-only. Confianza estadística de edge forward: media-baja hasta n≥50.

## Possibilities scanned
- miss_matrix scenarios: **375**
- stress bankroll rows: **24**
- evidence loss paths: **6**
- order/LOO variants: **18**
- ops failure modes: **7**
- deep_verify layers: **13/13**
- hyperreal book_walks: **48**

## Requirements
- `deep_verify`=PASS
- `stress_bankrolls`=PASS
- `miss_matrix_recommended`=PASS
- `evidence_adversity`=PASS
- `order_robustness`=PASS
- `ops_failure_modes`=PASS
- `market_states`=PASS

## ASSURED (sí)
- Postura SAFE: armed=0, dry_run=1, sin ALLOW_REARM/CONFIRM (verificado en proceso).
- DNA live canónico intacto: press-only ≤0.50 / leg≤0.39 / underdispersion / BJ≤0.50.
- Adversarios max-PnL fallan el gate long-term (no se promueven).
- Mecanismo de income + bankrolls base/hostile en escalas $100/$200 positivos (sobre sample DNA).
- Depósito runway $100: sobrevive misses 1–3 a budget $12/$25 (matriz exhaustiva).
- Auto-execute permanece bloqueado en todos los paths de pérdidas forzadas actuales.
- Dual-control / scripts live se niegan sin confirmación explícita.
- Sin take DNA ahora ≠ fallo de depósito: puedes fondear y esperar edge (watch-only).
- Capital actual ~$3.45 NO es runway operable a $25/trade; el depósito lo corrige.

## NOT ASSURED (no miento)
- NO se asegura beneficio futuro ni WR=100% forward (sample DNA n≈11; Wilson≈0.74 < 0.80).
- NO se asegura que aparezca un take DNA mañana (mercado puede seguir rico / sin UD).
- NO se habilita auto-execute (hace falta n≥50 y Wilson≥0.80).
- NO se asegura fill perfecto en CLOB en el momento del trade (abort-partial existe; FAK).
- NO se asegura contra black-swan de estación/oracle/geo/API (mitigado, no eliminado).
- Sims históricas ≠ garantía out-of-sample; por eso el rearm exige más evidencia.

## Reglas del inversor
- Depositar $100 (stretch $200) solo como runway watch-only.
- Tras depositar: NO armar, NO ALLOW_REARM, dejar PM2 research corriendo.
- Primera sesión real solo cuando status=READY_TO_REARM: budget $12 / cap $25.
- Si hay miss: parar sesión; no martingale; no aflojar DNA.
- Si geo/API falla: no operar desde entorno bloqueado.

## Deep verify
- `{'verdict': 'DEEP_VERIFY_DEPOSIT_RUNWAY_PASS', 'score': '13/13', 'passed': True, 'source': 'live_run'}`

## Hyperreal / mercado
- `{'verdict': 'HYPERREAL_MARKET_LIVE_OK', 'source': 'cached_latest', 'coverage': {'events_open_pack': 49, 'book_reports': 48, 'fillable_budget25_any': 18, 'case_matrix': {'n_unique_open_rows': 49, 'skip_taxonomy': {'basket_cost=0.604>max=0.5+max_leg=0.420>0.39+ev=-0.0279<0.01+not_underdispersed': 1, 'basket_cost=0.590>max=0.5+not_underdispersed': 1, 'basket_cost=0.730>max=0.5+max_leg=0.430>0.39': 1, 'basket_cost=0.580>max=0.5+not_underdispersed': 1, 'basket_cost=0.770>max=0.5': 1, 'open_only': 4, 'no_sleeve_for_city': 13, 'not_volatile': 6, 'unknown_station': 18, 'basket_cost=1.010>max=0.5+max_leg=0.580>0.39+ev=-0.0806<0.01+not_underdispersed': 1, 'basket_cost=0.900>max=0.5+max_leg=0.440>0.39': 1, 'basket_cost=0.990>max=0.5+max_leg=0.530>0.39+ev=-0.0451<0.01+not_underdispersed': 1}, 'gate_taxonomy': {'b0_l0_u0': 44, 'b0_l1_u0': 2, 'b0_l0_u1': 2, 'b0_l1_u1': 1}, 'liquidity_taxonomy': {'fillable_25': 18, 'abort_partial_25': 30}, 'counterfactual_n': 8, 'deposit_whatifs_n': 30, 'city_day_matrix_n': 49}}, 'wallet': {'balance_pusd': 3.4482, 'deposit_needed_to_100': 96.55, 'balance_error': None}}`

## Miss matrix (focus $100/$200/$500)
- checks=`{'dep100_budget25_miss1_tradeable': True, 'dep100_budget25_miss2_tradeable': True, 'dep100_budget25_miss3_tradeable': True, 'dep100_budget12_miss5_tradeable': True, 'raw_balance_blocks_budget25': True, 'no_ruin_in_recommended_1to3': True}`
- focus_ruin_n=4 recommended_ok_n=24
- dep=100.0 budget=12.0 misses=1 left=91.4482 status=ok_tradeable
- dep=100.0 budget=12.0 misses=2 left=79.4482 status=ok_tradeable
- dep=100.0 budget=12.0 misses=3 left=67.4482 status=ok_tradeable
- dep=100.0 budget=12.0 misses=5 left=43.4482 status=ok_tradeable
- dep=100.0 budget=25.0 misses=1 left=78.4482 status=ok_tradeable
- dep=100.0 budget=25.0 misses=2 left=53.4482 status=ok_tradeable
- dep=100.0 budget=25.0 misses=3 left=28.4482 status=ok_tradeable
- dep=100.0 budget=25.0 misses=5 left=-21.5518 status=ruin

## Evidence adversity
- Auto-execute permanece bloqueado bajo todos los paths de pérdidas forzadas. Aun con 39 wins perfectos hasta n=50, Wilson=0.9286 SÍ desbloquearía READY_TO_REARM.
- checks=`{'today_auto_blocked': True, 'all_loss_paths_keep_auto_blocked': True, 'even_perfect_to_n50_checked': True, 'perfect_to_n50_wilson': 0.9286, 'perfect_to_n50_would_rearm': True}`

## Stress must ($100/$200 base+hostile)
- start=100.0 base income_positive=True end=727.9337 wr=1.0 dd=0.0
- start=100.0 hostile income_positive=True end=538.4516 wr=0.9091 dd=0.0009
- start=200.0 base income_positive=True end=1229.5652 wr=1.0 dd=0.0
- start=200.0 hostile income_positive=True end=919.5901 wr=0.9091 dd=0.0009

## Ops failure modes
- passed=True geo_blocked_here=False
- checks=`{'armed_accidentally_on': True, 'dry_run_off': True, 'allow_rearm_set': True, 'real_confirm_set': True, 'code_safety_fail': True, 'dual_control_bypass': True}`

## Invariantes
- Depositar ≠ operar. Watch-only hasta READY_TO_REARM.
- DNA no se relaja aunque el paper gane más PnL.
- Esta batería NO fabrica evidencia ni posts.
