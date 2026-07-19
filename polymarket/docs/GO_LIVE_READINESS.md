# Go-live readiness (2026-07-19)

## Veredicto paper
Ejecutar:
```bash
python3 -m polymarket.research.local_lab.go_live_arm_check
python3 -m polymarket.research.local_lab.go_live_gate --max-age-hours 3
```

Snapshot post-fix (bank/soft-cut en promo + size DNA):
- paralelo pulse@5: WR75% traded=8 · robust +1.04
- paralelo pulse@10: WR83% traded=12 · robust +1.59
- flow@5 paralelo post-fix: WR~86% traded=7 (creciendo)
- Live flags: `POLY_LIVE_ARMED=0` · `POLY_LIVE_DRY_RUN=1`

## DNA canónico
- @5: `maker_demo_promo_flow_c5.json` (champ) · backup `maker_demo_promo_pulse_c5.json`
- @10: `maker_demo_promo_pulse_c10.json`

## Runtime WR-first
- Bank verde / corte rojo cada poll en `preserve_selectivity` y labels promo/fusion/flow/pulse/bank
- `hard_bank_usdc` implícito (~0.08) evita loterías por salto de mid
- `apply_live_clob_floors` respeta size del DNA en preserve (no fuerza 5)
- Gate: evidencia fresca ≤3h, excluye `|net|>0.35`

## Armado (solo si gate READY_*)
1. `go_live_arm_check` → exit 0
2. Micro dry-run: `ARMED=1` `DRY_RUN=1` `MAX_CAPITAL=5`
3. Micro real: `DRY_RUN=0` `MAX_CAPITAL=2..5`
4. No escalar hasta sesión live estable

Paper ≠ live. Riesgo residual de fills/fees/latency.
