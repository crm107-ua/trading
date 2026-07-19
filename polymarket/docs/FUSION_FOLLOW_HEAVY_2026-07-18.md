# Fusion Follow — WR hunt (2026-07-19)

**Estado:** confirm v5 cerrado · **no** BOTH_READY · live SAFE  
**Mejor DNA:** `fusion_follow_flow` (`maker_fusion`, pulse OFF)

## Confirm v5 (8×5 min, feeds reales)

| DNA | @5 | @10 | BOTH |
|-----|----|-----|------|
| **fusion_follow_flow** | **WR 100%** (7W, +0.40) ✓ | WR 40% (2W/2F/1L, −0.14) ✗ | False |
| fusion_follow_heavy | WR 43% (−0.15) ✗ | WR 29% (−0.52) ✗ | False |

### Lectura
- `@5` flow banca +0.05 casi siempre vía `rule_grind_bank` — DNA válido ahí.
- `@10` rompe en follows tardíos (ask ~0.40–0.43) con gaps de 1 poll → −0.22/−0.28.
- Heavy demasiado agresivo tras el unfreeze de spot.

## v6 (en curso)
- Flow: banda dn más alta (0.38–0.48), roll≥1.6, size 3, max_loss 0.03
- Corte rojo inmediato ≤ −0.01 usdc cada poll (fusion/follow)

```bash
python3 -m polymarket.research.local_lab.confirm_dna_pair \
  --label fusion_follow_flow --strategy maker_fusion \
  --config maker_demo_fusion_follow_flow.json --sessions 8 --minutes 5
```
