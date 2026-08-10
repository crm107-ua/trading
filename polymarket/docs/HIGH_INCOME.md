# High income — mismo edge, más dólares

**Principio:** ganar más = **escalar tamaño** en takes press-only, no aflojar filtros.

| Escala | Depósito | $/trade | Cap sesión | EV hoy* | Semana* | Mes* |
|--------|----------|---------|------------|---------|---------|------|
| micro | $25 | ~$5 | $5 | ~$6 | ~$41 | ~$182 |
| standard | $50 | ~$12 | $15 | ~$14 | ~$99 | ~$437 |
| **high** | **$100** | **~$25** | **$50** | **~$29** | **~$206** | **~$910** |
| aggressive | $200 | ~$50 | $100 | ~$59 | ~$411 | ~$1820 |

\*Proyección sobre ~2.5 trades/semana históricos (WR press 100% en sample). **Hoy a menudo $0** si no hay basket ≤0.50.

## Qué NO hacer

- Meter tier `select` → WR ~77%
- Subir basket a 0.60 “para operar hoy” → peor calidad, poco extra vs sizing
- Forzar Shanghai 0.62 sin underdispersion

## Comandos

```bash
# Ver proyecciones
python3 -m polymarket.research.local_lab.high_income_project

# Estado high
python3 -m polymarket.research.local_lab.definitive_income_system --scale high

# Live high (región permitida + ≥$100)
POLY_LADDER_HIGH_INCOME=1 POLY_LADDER_REAL_CONFIRM=1 \
  python3 -m polymarket.research.local_lab.definitive_income_system \
    --scale high --income-loop --auto-execute --i-accept-real-loss YES \
    --rounds 40 --interval 180
```

Config: `polymarket/config/weather_ladder_high_income.json`
