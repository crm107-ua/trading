# Preparación con más capital (DNA intacta)

**UTC:** `2026-08-10T13:33:02.182479+00:00`
**DNA takes:** n=11 WR=1.0 pnl_units=659.41
**Long-term:** `LONG_TERM_ROBUST` profile=`income_wr80`

> Mejorar ingreso = **escalar capital** sobre el mismo edge durable. No aflojar basket/UD/select. **No depositar** hasta READY_TO_REARM.

## Escala recomendada (objetivo)

| Escala | Depósito | $/trade | Cap sesión | Misses buffer | Semana cons. | Mes cons. |
|--------|----------|---------|------------|---------------|--------------|-----------|
| **micro** | $25 | ~$5 | $5 | 1 (runway=5) | $22.88 | $98.07 |
| **standard** | $50 | ~$12 | $15 | 2 (runway=4) | $54.92 | $235.38 |
| **high** | $100 | ~$25 | $50 | 2 (runway=4) | $114.42 | $490.37 |
| **aggressive** | $200 | ~$50 | $100 | 3 (runway=4) | $228.84 | $980.74 |
| **pro** | $500 | ~$75 | $150 | 4 (runway=6) | $343.26 | $1471.12 |
| **desk** | $1000 | ~$100 | $200 | 5 (runway=10) | $457.68 | $1961.49 |

## Bankroll compound (DNA + fricción)

- $100 `base`: n=11 WR=1.0 pnl=627.9337 end=727.9337 mult=7.2793 dd=0.0
- $100 `hostile`: n=11 WR=0.9091 pnl=438.4516 end=538.4516 mult=5.3845 dd=0.0009
- $200 `base`: n=11 WR=1.0 pnl=1029.5652 end=1229.5652 mult=6.1478 dd=0.0
- $200 `hostile`: n=11 WR=0.9091 pnl=719.5901 end=919.5901 mult=4.598 dd=0.0009
- $500 `base`: n=11 WR=1.0 pnl=2018.3854 end=2518.3854 mult=5.0368 dd=0.0
- $500 `hostile`: n=11 WR=0.9091 pnl=1397.0838 end=1897.0838 mult=3.7942 dd=0.0009
- $1000 `base`: n=11 WR=1.0 pnl=2922.0748 end=3922.0748 mult=3.9221 dd=0.0
- $1000 `hostile`: n=11 WR=0.9091 pnl=1999.0868 end=2999.0868 mult=2.9991 dd=0.0008

## Recomendación de preparación

- **Target deposit (cuando gates verdes):** `$100.0` (high)
- **Primera sesión:** budget `$12.0` · cap `$25.0`
- **Por qué:** Con más capital ($100→$200) el mismo DNA durable genera más $/semana. Hoy n=11<50 → preparar wallet/región/playbook, NO depositar aún. $100 sobrevive ≥4 misses @~$25/trade; $200 runway≈4.
- **can_recommend_deposit_now:** `False`

## Checklist prep (orden)

1. Mantener WATCH_ONLY + forward snapshots hasta n≥50 / Wilson≥0.80.
2. Re-certificar: `long_term_robustness --write-docs` + `simulate_real_income`.
3. Cuando READY_TO_REARM: depositar **$100** (escala high), no $3.
4. Primera semana real: budget $12–$25, cap sesión $25–$50, max 1 ciudad.
5. Si 2 semanas limpias: subir a aggressive ($200 / $50/trade) sin tocar DNA.
6. Pro/desk ($500–$1000) solo con runway de misses y misma DNA.
7. SAFE al terminar cada sesión; un miss → revisar, no doblar.

## Qué NO hacer

- Aflojar DNA para “operar ya” con más capital
- Depositar con n≪50 / Wilson≪0.80
- Martingale tras un miss
- Subir $/trade por encima del cap de la escala

Ver: [`HIGH_INCOME.md`](HIGH_INCOME.md) · [`LONG_HORIZON_OPTIMAL.md`](LONG_HORIZON_OPTIMAL.md) · [`PREPARE_REAL_MONEY.md`](PREPARE_REAL_MONEY.md)
