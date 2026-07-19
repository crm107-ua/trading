# Certificación pulse@10 — CERTIFIED (2026-07-19)

## Veredicto: CERTIFIED histórico · PRO pendiente de WR fresco
El DNA y el motor PRO están listos; **no armar real** hasta `PRO_CERTIFIED` (WR fresco ≥80%).

| Check | Resultado |
|-------|-----------|
| Paper WR decisivo (pico) | **83.3%** (cert anterior) |
| Paper WR fresco (ahora) | **~72%** → bloquea PRO |
| Dry CLOB paralelo fusion | **OK** · fills dry · residual 0 · balance intacto |
| Flags | `ARMED=0` `DRY_RUN=1` (SAFE) |

## Upgrade PRO (2026-07-19)
Ver **`docs/PRO_DESK_PLAYBOOK.md`** y:

```bash
python3 -m polymarket.research.local_lab.certify_pro_desk
python3 -m polymarket.research.local_lab.first_investment_playbook
```

Cambios críticos:
- `live_maker` usa **`maker_fusion`** (paridad paper), no `maker_edge`
- Config micro: `maker_demo_promo_pulse_c10_micro_live.json` (capital 1.5)
- Dry smoke ya no contamina inventario (opt-in `POLY_LIVE_DRY_SMOKE_POST=1`)
- Paralelismo con stagger + haircut ρ≈0.85

## DNA
- Paper: `maker_demo_promo_pulse_c10.json`
- Live locked: `maker_demo_promo_pulse_c10_live.json`
- **Micro real:** `maker_demo_promo_pulse_c10_micro_live.json`

## Armado (obligatorio en este orden)
```bash
# 1) Dry operativo 30–60 min
export POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=1 POLY_LIVE_MAX_CAPITAL_USDC=5
export POLY_LIVE_DRY_SMOKE_POST=0
python3 -m polymarket.research.local_lab.live_maker \
  --config polymarket/config/maker_demo_promo_pulse_c10_micro_live.json \
  --strategy maker_fusion --minutes 45

# 2) Micro real (solo si dry sano)
export POLY_LIVE_DRY_RUN=0 POLY_LIVE_MAX_CAPITAL_USDC=1.5
# mismo comando live_maker

# 3) Tras sesión / si algo raro:
export POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1
```

## Reglas duras
- **No** empezar con 10€ de capital live; micro 1.5→2→3→5
- **No** armar @5 ni Shadow
- Matar si hay `FLATTEN_WRONG_TOKEN` / residual inventory en **real**
- Re-certificar PRO si WR fresco (3h) cae &lt;80%
