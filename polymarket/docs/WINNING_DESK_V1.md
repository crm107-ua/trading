# Winning Desk v3 — estrategia paper ganadora (multi-sleeve)

**Estado:** paper lab · **no** on-chain · no proyección anual  
**Fecha:** 2026-08-09 · dataset **90** mercados resueltos

## Resultado congelado

| Sleeve | Universo | Research |
|--------|----------|----------|
| **core** | SG / Shanghai / HK | WR **100%** · +$218 |
| **beijing** | Beijing (bias+1.0) | WR **100%** · +$405 |
| **unión + floor gate** | ambos | WR **100%** (13/13) · **+$623.55** · OOS WR **100%** (7/7) |

## Gate crítico (v3)

Saltar si `center_temp < min(point_buckets)` — evita el trap open-low  
(ej. Beijing 2026-07-10: center 27, buckets ≥28, winner «27°C or below»).

## Referencia de mercado: `macau.weather`

Wallet live de ladder HK (highest+lowest, ~+$10k). Ver `docs/MACAU_WEATHER_BOT.md`. Copiamos **universo HK + disciplina cheap-basket**, no su width/basket caros.

## Rechazado

- Seoul, Taipei volume, basket≤0.65 overfit, bias global único

## Paper replay (12d)

- Pre-gate session: **9/9** · **+$418.62** · equity $150→$568  
- El floor gate solo habría omitido pérdidas open-low (no estaba en esa ventana)

## Comandos

```bash
python -m polymarket.research.local_lab.validate_two_tier
python -m polymarket.research.local_lab.kfold_champion
python -m polymarket.research.local_lab.weather_ladder_paper \
  --config polymarket/config/weather_ladder_champion_v2.json
```

## Config

`polymarket/config/weather_ladder_champion_v2.json` (sleeves + floor gate en `ladder.py`)
