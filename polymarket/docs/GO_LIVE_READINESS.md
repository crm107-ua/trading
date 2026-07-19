# Go-live readiness (2026-07-19)

## Veredicto
**READY_STRICT** (paper, evidencia fresca ≤3h). Live sigue SAFE hasta armado manual.

```bash
python3 -m polymarket.research.local_lab.go_live_arm_check   # exit 0
python3 -m polymarket.research.local_lab.go_live_gate --max-age-hours 3
```

### Snapshot (gate fresco)
| Evidencia | WR decisivo | decisive | robust PnL |
|-----------|-------------|----------|------------|
| paralelo @5 (pulse) | **82.4%** | 17 | +1.12 |
| paralelo @10 (pulse) | **86.7%** | 15 | +1.34 |

WR = wins/(wins+losses); flats/outliers fuera. Live: `ARMED=0` `DRY_RUN=1`.

## DNA canónico
- @5: `maker_demo_promo_pulse_c5.json` (champ) · backup `maker_demo_promo_flow_c5.json`
- @10: `maker_demo_promo_pulse_c10.json`

## Armado (manual)
1. `go_live_arm_check` exit 0
2. Micro dry-run: `ARMED=1` `DRY_RUN=1` `MAX_CAPITAL=5`
3. Micro real: `DRY_RUN=0` `MAX_CAPITAL=2..5` (solo si dry sano)
4. No escalar hasta sesión live estable

Paper ≠ live (fees, latency, fills). Riesgo residual real.
Revalidar si el gate vuelve a NOT_READY:
```bash
python3 -m polymarket.research.local_lab.revalidate_until_ready --waves 4 --sessions 6 --lines 4
```
