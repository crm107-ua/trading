# Shadow OFIR — síntesis edge “desk privado” (2026-07-19)

## Honestidad
No existe un “secreto filtrado” usable de un bot privado concreto. Los desks
que ganan en Polymarket 2026 comparten un **stack** (público a trozos, privado
como ensamblaje):

1. **Latency lead** — spot (Binance/OKX/…) se mueve 30–90s antes que el mid
2. **Toxicity / OFIR** — no cotizar contra imbalance de libro (adverse selection)
3. **Signal guard / mid-lag** — solo si el mid aún no catchupeó el move
4. **Settlement blackout** — evitar cola MEV de resolución
5. **Maker + bank/cut rápido** — no lotería de inventario

`maker_shadow_ofir` empaqueta ese stack en un DNA operable (`fusion_enable_shadow`).

## Configs
- `maker_demo_promo_shadow_c5.json`
- `maker_demo_promo_shadow_c10.json`

## Confrontación
```bash
python3 -m polymarket.research.local_lab.confront_shadow_vs_pulse \
  --sessions 8 --minutes 5 --lines 4
```

Compara Shadow vs Pulse champ @5/@10 en feeds reales (paper).
