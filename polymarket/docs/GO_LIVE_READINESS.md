# Go-live readiness — bank DNA (2026-07-19)

## Objetivo
Paper realista con **WR excelente (≥75% robusto)** @5€ y @10€, paralelo multi-línea, antes de capital real.

## DNA canónico
- @10: `maker_demo_promo_fusion_c10.json` / `maker_demo_promo_bank_c10.json` (`fusion_c10_bank`)
- @5: `maker_demo_promo_bank_c5.json` (mismo DNA)

## Por qué “robusto”
Hubo wins paper de **+1.00** por hold de inventario sin bankear verde (lotería mid).  
Runtime ahora **bankea verde cada poll** (`grind_bank`). El gate excluye `|net|>0.35` del WR.

## Gate
```bash
python3 -m polymarket.research.local_lab.go_live_gate
```
- `READY_STRICT`: dual WR75 robusto + paralelo @5 y @10 WR70 + SAFE flags  
- `READY_RISK_ON`: al menos un capital @5 y @10 en WR alto + SAFE  
- `NOT_READY`: seguir paper

## Live (solo cuando READY_*)
1. Micro dry-run: `POLY_LIVE_ARMED=1` + `POLY_LIVE_DRY_RUN=1`  
2. Micro real: `DRY_RUN=0` + `POLY_LIVE_MAX_CAPITAL_USDC` bajo (1–5)  
3. Nunca armar sin el gate en verde

Flags actuales deben seguir `ARMED=0` hasta decisión explícita del operador.
