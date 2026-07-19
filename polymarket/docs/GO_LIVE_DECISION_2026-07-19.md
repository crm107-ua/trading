# Decisión go-live — actualizado 2026-07-19 (PRO desk)

## Veredicto actual
| Camino | Estado |
|--------|--------|
| **PRO_CERTIFIED** pulse@10 | **NO** — WR fresco ~72% (barra ≥80%) |
| Dry CLOB paralelo `maker_fusion` | **OK** — 2×2 fills, residual 0, balance intacto, paridad paper↔live |
| pulse@5 / Shadow | **NO armar** |

## Por qué no invertir aún
El DNA y el motor PRO están listos, pero la **evidencia paper fresca (≤3h)** bajó del pico 83% a ~72% en régimen de mids extremos. No se arma capital real hasta recuperar WR≥80%.

## Qué ya está “pionero” y listo
1. `live_maker` ejecuta **`maker_fusion`** (misma ruta que paper)
2. Micro config CLOB-viable: **5 USDC** (`maker_demo_promo_pulse_c10_micro_live.json`)
3. Desk risk: ρ=0.85, stagger, ladder, EV corr-adjusted
4. Dry multi-línea real sin mover saldo (~10.93 pUSD intacto)
5. Playbook: `docs/PRO_DESK_PLAYBOOK.md` + `first_investment_playbook`

## Paralelo
Colisión misma market medida ~67% → **máx 2 líneas live**, stagger ≥45–90s. EV ≈ 1.15× una línea, no 2×.

## Re-certificar
```bash
python3 -m polymarket.research.local_lab.certify_pro_desk \
  --waves 1 --sessions 8 --lines 2 --stagger-s 90 --dry-lines 2 --dry-minutes 8
python3 -m polymarket.research.local_lab.first_investment_playbook
```

Cuando salga `PRO_CERTIFIED`, primera inversión = dry 45m → real 30m con capital **5**, luego SAFE.
