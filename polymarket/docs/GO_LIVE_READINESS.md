# Go-live readiness (2026-07-19)

## Objetivo
Paper realista con **WR excelente (≥75% robusto)** @5€ y @10€, paralelo multi-línea, antes de capital real.

## DNA canónico
- @5: `maker_demo_promo_flow_c5.json` (champ) · backup `maker_demo_promo_pulse_c5.json`
- @10: `maker_demo_promo_pulse_c10.json` (champ fresco) · backup `maker_demo_promo_fusion_c10.json` (bank)

## Por qué “robusto”
Hubo wins paper de **+1.00** por hold de inventario sin bankear verde (lotería mid).
Runtime **bankea verde / corta rojo cada poll** en labels promo/fusion/flow/pulse (`preserve_selectivity`).
El gate excluye `|net|>0.35` del WR y solo cuenta evidencia **fresca** (`--max-age-hours`).

## Gate
```bash
python3 -m polymarket.research.local_lab.go_live_gate --max-age-hours 3
```
- `READY_STRICT`: dual WR75 robusto + paralelo @5 y @10 WR70 traded≥8 + SAFE flags
- `READY_RISK_ON`: WR75 @5 y @10 + al menos un paralelo 70 + SAFE
- `NOT_READY`: seguir paper

## Live (solo cuando READY_*)
1. Micro dry-run: `POLY_LIVE_ARMED=1` + `POLY_LIVE_DRY_RUN=1`
2. Micro real: `DRY_RUN=0` + `POLY_LIVE_MAX_CAPITAL_USDC` bajo (1–5)
3. Nunca armar sin el gate en verde

Flags actuales deben seguir `ARMED=0` hasta decisión explícita del operador.
