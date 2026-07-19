# Certificación pulse@10 — CERTIFIED (2026-07-19)

## Veredicto: CERTIFIED
Listo para **micro inversión real** con este DNA únicamente.

| Check | Resultado |
|-------|-----------|
| Paper WR decisivo (≤3h) | **83.3%** (30W/6L, decisive=36) |
| PnL robusto | **+2.33** |
| Dry-run CLOB | `LIVE_DRY_RUN` · 2 fills dry · balance **10.9277** intacto |
| Flags | `ARMED=0` `DRY_RUN=1` (SAFE hasta que armes) |

## DNA
- Paper/Live: `maker_demo_promo_pulse_c10.json`
- Alias locked: `maker_demo_promo_pulse_c10_live.json` (**misma config**)

## Armado (obligatorio en este orden)
```bash
# 1) Dry operativo 30–60 min
export POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=1 POLY_LIVE_MAX_CAPITAL_USDC=5
python3 -m polymarket.research.local_lab.live_maker \
  --config polymarket/config/maker_demo_promo_pulse_c10_live.json --minutes 30

# 2) Micro real (solo si dry sano)
export POLY_LIVE_DRY_RUN=0 POLY_LIVE_MAX_CAPITAL_USDC=2   # luego 3..5
# mismo comando live_maker

# 3) Tras sesión / si algo raro:
export POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1
```

## Reglas duras
- **No** empezar con 10€ de capital live; micro 2→5
- **No** armar @5 ni Shadow
- Matar si hay `FLATTEN_WRONG_TOKEN` / residual inventory en **real** (en dry es artefacto)
- Re-certificar si WR fresco (3h) cae &lt;80%:
  `python3 -m polymarket.research.local_lab.certify_pulse_c10`

## Re-certificar
```bash
python3 -m polymarket.research.local_lab.certify_pulse_c10 \
  --config maker_demo_promo_pulse_c10.json --label promo_pulse_c10 \
  --waves 1 --sessions 6 --lines 4 --dry-minutes 5
```
