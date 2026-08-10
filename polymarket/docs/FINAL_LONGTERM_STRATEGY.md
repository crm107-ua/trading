# Estrategia final a largo plazo

**Config canónica:** `polymarket/config/weather_ladder_final_longterm.json`
**Óptimo durable:** [`LONG_HORIZON_OPTIMAL.md`](LONG_HORIZON_OPTIMAL.md)
**Sistema de producción:** [`DEFINITIVE_INCOME_SYSTEM.md`](DEFINITIVE_INCOME_SYSTEM.md)
**Veredicto:** `LONG_TERM_ROBUST` · profile=`income_wr80`

## Qué la hace durable (no solo “ahora”)

| Regla | Por qué |
|-------|---------|
| Solo `press_under` | El tier `select` / sin UD baja WR y rompe semanas/ciudades |
| Underdispersion obligatoria | Evita entradas con ensemble disperso |
| Beijing basket ≤ 0.50 | Mata la pérdida open-skew a basket 0.55+ |
| Sizing wing-safe + `max_per_city` | No quema bankroll; hits en ala siguen PnL>0 |
| Objetivo = robustez | Walk-forward / mitades / leave-one-city / fricción — **no** max PnL paper |

## Certificación

Universo 128 cases (2026-07-10 → 2026-08-10):

- Overall **11/11** WR=1.0 pnl=659.41
- Walk-forward OOS WR=1.0 n=10
- Score durable=540.2

## Adversarios puntuales (rechazados)

- `punctual_basket58_no_ud`: WR=0.7727 pnl=767.63 → `NOT_LONG_TERM_YET`
- `punctual_basket52_leg36_no_ud`: WR=0.84 pnl=1083.98 → `NOT_LONG_TERM_YET`
- `punctual_select_core`: WR=0.8 pnl=1079.9 → `NOT_LONG_TERM_YET`

## Operación

```bash
python3 -m polymarket.research.local_lab.long_term_robustness --write-docs
python3 -m polymarket.research.local_lab.definitive_income_system
python3 -m polymarket.research.local_lab.simulate_real_income
```

## Límite honesto

Robustez sobre ~30 días de weather Polymarket. No hay un año de historia; la garantía es estructural (press-only + UD + anti-overfit). Más ingreso durable = más capital y más evidencia forward, no filtros más flojos.
