# High income — mismo edge, más dólares

**Principio:** ganar más = **escalar tamaño** en takes press-only, no aflojar filtros.
**Prep capital:** [`CAPITAL_SCALE_PREP.md`](CAPITAL_SCALE_PREP.md)
**Óptimo LT:** [`LONG_HORIZON_OPTIMAL.md`](LONG_HORIZON_OPTIMAL.md)

| Escala | Depósito | $/trade | Semana limpia | Semana conservadora | Mes limpio | Mes conservador |
|--------|----------|---------|---------------|---------------------|------------|-----------------|
| micro | $25 | ~$5 | ~$40.15 | ~$22.88 | ~$172.06 | ~$98.07 |
| standard | $50 | ~$12 | ~$96.35 | ~$54.92 | ~$412.94 | ~$235.38 |
| **high** | **$100** | **~$25** | **~$200.74** | ~$114.42 | ~$860.3 | ~$490.37 |
| **aggressive** | **$200** | **~$50** | **~$401.47** | ~$228.84 | ~$1720.6 | ~$980.74 |
| pro | $500 | ~$75 | ~$602.21 | ~$343.26 | ~$2580.9 | ~$1471.12 |
| desk | $1000 | ~$100 | ~$802.95 | ~$457.68 | ~$3441.21 | ~$1961.49 |

\*Conservador = haircut ×0.57 (fricción hostil + floors).

## Target de preparación

- Depositar **$100** (high) cuando `READY_TO_REARM` — no antes.
- Stretch **$200** tras semanas limpias.
- Primera sesión real: budget `$12.0`, cap `$25.0`.
- can_recommend_deposit_now=`False` (evidencia aún corta).

## Qué NO hacer

- Meter tier `select` / quitar UD / basket >0.50
- Forzar trades sin edge para “usar el capital”

## Comandos

```bash
python3 -m polymarket.research.local_lab.prepare_capital_scale --write-docs
python3 -m polymarket.research.local_lab.high_income_project
python3 -m polymarket.research.local_lab.long_term_robustness --write-docs
python3 -m polymarket.research.local_lab.real_env_ready --scale high
```

Config high: `polymarket/config/weather_ladder_high_income.json`
