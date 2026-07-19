# PRO Desk — pulse@10 (pionero, listo para micro real)

## Qué es “PRO_CERTIFIED”
Certificación más dura que `CERTIFIED` básica:

| Barra | Umbral |
|-------|--------|
| WR decisivo fresco (≤3h) | ≥ **80%** |
| Trades decisivos | ≥ **20** |
| PnL robusto | ≥ **+0.75** |
| Paralelo staggered | WR ≥ **75%**, decisive ≥ **12** |
| Dry CLOB multi-línea | `DRY_PARALLEL_OK` + paridad `maker_fusion` |
| Inventario residual dry | ≈ 0 (smoke ya no contamina) |

## Ventaja vs competencia
1. **Paridad paper↔live**: `live_maker` ejecuta `maker_fusion` (Pulse+Follow), no `maker_edge`.
2. **Bank/cut fusionish en live** (mismo espíritu que paper).
3. **Paralelismo con stagger + haircut ρ≈0.85** (no vende N× falso).
4. **Risk budget de desk** + ladder 1.5→2→3→5.
5. **Dry multi-línea real** contra CLOB sin mover saldo.

## DNA
- Paper: `maker_demo_promo_pulse_c10.json`
- Micro live: `maker_demo_promo_pulse_c10_micro_live.json` (capital **1.5**)
- Strategy: `maker_fusion` (`fusion_enable_pulse/follow=true`, edge off)

## Certificar
```bash
python3 -m polymarket.research.local_lab.certify_pro_desk \
  --waves 1 --sessions 6 --lines 4 --dry-lines 2 --dry-minutes 5
python3 -m polymarket.research.local_lab.first_investment_playbook
```

## Primera inversión (orden obligatorio)
```bash
# 0) SAFE
export POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1 POLY_LIVE_MAX_CAPITAL_USDC=1.5

# 1) Dry 30–60 min
export POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=1 POLY_LIVE_MAX_CAPITAL_USDC=5
export POLY_LIVE_DRY_SMOKE_POST=0
python3 -m polymarket.research.local_lab.live_maker \
  --config polymarket/config/maker_demo_promo_pulse_c10_micro_live.json \
  --strategy maker_fusion --minutes 45

# 2) Dry paralelo (opcional)
python3 -m polymarket.research.local_lab.run_live_dry_parallel \
  --lines 2 --minutes 15 --stagger-s 45

# 3) MICRO REAL — solo si dry sano
export POLY_LIVE_DRY_RUN=0 POLY_LIVE_MAX_CAPITAL_USDC=1.5
python3 -m polymarket.research.local_lab.live_maker \
  --config polymarket/config/maker_demo_promo_pulse_c10_micro_live.json \
  --strategy maker_fusion --minutes 30

# 4) SAFE
export POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1
```

## Previsión de ganancia (orientativa)
Medida sobre paper fresco pulse@10 (WR≈83%, EV/fill≈+0.07 USDC).  
**Haircut de correlación** en paralelo (ρ=0.85):

| Escenario | EV corr-adjusted |
|-----------|------------------|
| 1 línea · 1h | ~+0.35 a +0.50 USDC (banda p25–base; fill-rate depende) |
| 2 líneas · 1h | ~1.15× una línea (NO 2×) |
| 8h · 1 línea | ~8× la hora, con cola de drawdown |

Reglas:
- Usa `pnl_corr_adjusted_usdc`, nunca N× naive.
- Paper ≠ live (fees, latency, fills parciales).
- No empezar con 10€. Ladder: **1.5 → 2 → 3 → 5**.

## Kill switches
- `FLATTEN_WRONG_TOKEN` / `DUST_STUCK` / residual en **real**
- WR vivo &lt; 60% en ≥6 trades
- `KILL_SESSION` / `KILL_DAY`
- Degradación adverse vs paper

## No armar
- pulse@5, Shadow OFIR, ni configs con capital 10 en live directo.
