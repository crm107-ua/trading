# Fusion Follow-Heavy — WR-first (2026-07-18/19)

**Estado:** @5 confirm PASS (WR100%) · @10 FAIL (WR33%) → follow-only retighten · **no** on-chain  
**Estrategia runtime:** `maker_fusion`  
**Config:** `maker_demo_fusion_follow_heavy.json`

## DNA (v2 follow-only)

1. **Pulse OFF** (`fusion_enable_pulse=false`) — evita asks tóxicos mid-ventana  
2. **Follow** con `follow_min_fair_edge`, roll/vel más altos, banda estrecha, persist≥2  
3. **Edge OFF** — el fade barato sin momentum era la fuente de rojas  
4. Size 4 + `max_loss` 0.04 + soft-cut 40% + flatten a bid/ask ejecutable

## Confirm pair (pre-retighten)

| Capital | Traded | WR | Total | ¿PASS? |
|---------|--------|----|-------|--------|
| 5€ | 2 | **100%** | +0.13 | sí |
| 10€ | 3 | 33% (1W/1L/1F) | +0.07 | no (worst −0.10) |

## Re-confirm

```bash
python3 -m polymarket.research.local_lab.confirm_dna_pair \
  --label fusion_follow_heavy --strategy maker_fusion \
  --config maker_demo_fusion_follow_heavy.json --sessions 8 --minutes 5
```

Criterio promo: WR≥70% traded≥2 en **ambos** capitals con el **mismo** DNA.
