# Fusion Follow-Heavy — champion candidate (2026-07-18)

**Estado:** scout positivo @5€ · confirm @5/@10 en curso · **no** on-chain  
**Estrategia runtime:** `maker_fusion`  
**Config:** `maker_demo_fusion_follow_heavy.json`

## DNA

1. **Pulse** (latencia roll/mid-lag) si dispara  
2. **Follow** (unirse al mid 0.50–0.74 / 0.26–0.50 solo si spot confirma)  
3. **Edge OFF** — el fade barato sin momentum era la fuente de rojas

## Scout wave (multi-DNA, feeds reales)

| Capital | DNA | Traded | WR | Total |
|---------|-----|--------|----|-------|
| 5€ | fusion_follow_heavy | 2 | **100%** (2W/0L) | **+0.34** |
| 5€ | fusion_edge_mom | 1 | 100% | +0.33 |
| 5€ | fusion_base | 1 | 100% | +0.22 |
| 10€ | fusion_base | 1 | 100% | +0.22 |

## Multi-DNA scout (cerrado)

| Capital | Mejor DNA | Traded | WR | Total | ¿PASS? |
|---------|-----------|--------|----|-------|--------|
| 5€ | fusion_follow_heavy | 2 | 100% | +0.34 | sí |
| 10€ | selective_mom | 4 | 75% | +0.37 | sí (DNA distinto) |
| 10€ | fusion_follow_heavy | 1 | 100% | +0.12 | falta traded≥2 |

**No** promover mezcla de DNAs. Confirm por DNA:

```bash
python -m polymarket.research.local_lab.confirm_dna_pair \
  --label fusion_follow_heavy --strategy maker_fusion \
  --config maker_demo_fusion_follow_heavy.json --sessions 8 --minutes 5

python -m polymarket.research.local_lab.confirm_dna_pair \
  --label selective_mom --strategy maker_edge \
  --config maker_demo_selective_mom.json --sessions 8 --minutes 5
```

Criterio promo: WR≥70% traded≥2 en **ambos** capitals con el **mismo** DNA.
