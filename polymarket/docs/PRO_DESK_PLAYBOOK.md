# PRO Desk — pulse@10 (pionero, listo para micro real)

## Qué es “PRO_CERTIFIED”
Certificación más dura que `CERTIFIED` básica:

| Barra | Umbral |
|-------|--------|
| WR decisivo fresco (≤3h) | ≥ **80%** |
| Trades decisivos | ≥ **20** |
| PnL robusto | ≥ **+0.75** |
| Paralelo staggered (label pro) | WR ≥ **75%**, decisive ≥ **12** |
| Dry CLOB multi-línea | `DRY_PARALLEL_OK` + **≥1 fill dry** + paridad `maker_fusion` |
| Inventario residual dry | ≈ 0 |

## Ventaja vs competencia
1. **Paridad paper↔live**: `live_maker` ejecuta `maker_fusion` (Pulse+Follow).
2. **Bank/cut fusionish en live**.
3. **Paralelismo con stagger + haircut ρ≈0.85** (colisión medida; no vende N×).
4. **Risk budget de desk** + capital micro **5 USDC** (mínimo CLOB-viable).
5. **Dry multi-línea real** contra CLOB sin mover saldo.

## DNA
- Paper: `maker_demo_promo_pulse_c10.json`
- Micro live: `maker_demo_promo_pulse_c10_micro_live.json` (**capital 5**)
- Strategy: `maker_fusion`

> Nota: 1.5 USDC **no es operable** con floor CLOB de 5 shares (notional típico 2–3.5).

## Certificar
```bash
python3 -m polymarket.research.local_lab.certify_pro_desk \
  --waves 1 --sessions 8 --lines 2 --stagger-s 90 --dry-lines 2 --dry-minutes 8
python3 -m polymarket.research.local_lab.first_investment_playbook
```

## Primera inversión
```bash
export POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1 POLY_LIVE_MAX_CAPITAL_USDC=5

export POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=1 POLY_LIVE_DRY_SMOKE_POST=0
python3 -m polymarket.research.local_lab.live_maker \
  --config polymarket/config/maker_demo_promo_pulse_c10_micro_live.json \
  --strategy maker_fusion --minutes 45

# Si dry sano (fills dry + residual 0 + balance intacto):
export POLY_LIVE_DRY_RUN=0 POLY_LIVE_MAX_CAPITAL_USDC=5
python3 -m polymarket.research.local_lab.live_maker \
  --config polymarket/config/maker_demo_promo_pulse_c10_micro_live.json \
  --strategy maker_fusion --minutes 30

export POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1
```

## Paralelismo
- Live: **máx 2 líneas**, stagger ≥45–90s
- Colisión misma market ≈ alta → EV usa `pnl_corr_adjusted` (ρ=0.85)
- 2 líneas ≈ **1.15×** una línea, no 2×

## Kill switches
`FLATTEN_WRONG_TOKEN` / `DUST_STUCK` / residual / WR vivo &lt;60% / `KILL_SESSION` / `KILL_DAY`
