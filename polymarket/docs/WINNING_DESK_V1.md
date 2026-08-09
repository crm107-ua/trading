# Winning Desk v2 — estrategia paper ganadora (multi-sleeve)

**Estado:** paper lab · **no** on-chain · no proyección anual  
**Fecha:** 2026-08-09 · dataset **90** mercados resueltos

## Estrategia congelada

| Sleeve | Universo | Filtros | Evidencia |
|--------|----------|---------|-----------|
| **core** | Singapore, Shanghai, Hong Kong | basket≤0.50 · pierna≤0.39 · bias+0.5 · press_under→select | WR **100%** (6/6) · +**$218** |
| **beijing** | Beijing | basket≤0.55 · pierna≤0.39 · bias+1.0 · press_under→select | WR **87.5%** (7/8) · +**$392** |
| **union** | ambos | sin overlap de ciudades | WR **92.9%** (13/14) · +**$609.75** · OOS WR **100%** (7/7, +$258) |

## Rechazado

- Seoul (0% histórico)
- Taipei / volume basket≤0.65 (overfit; WR cae al ampliar muestra)
- Bias único global (rompe SG o Beijing según el valor)

## Reglas

1. Asignar ciudad → sleeve → tiers (press under primero).
2. Entry: ask live o CLOB pre-spike.
3. Settlement: winner 100¢.
4. Maker solo capital idle.
5. `POLY_LIVE_ARMED=0` hasta gate explícito.

## Comandos

```bash
python -m polymarket.research.local_lab.validate_two_tier
python -m polymarket.research.local_lab.weather_ladder_paper \
  --config polymarket/config/weather_ladder_champion_v2.json
python -m polymarket.research.local_lab.winning_desk --maker-rounds 0
```

## Config

`polymarket/config/weather_ladder_champion_v2.json` (`sleeves` + `resolved_max_age_days` para replay paper).
