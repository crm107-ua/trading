# High income — mismo edge, más dólares

**Principio:** ganar más = **escalar tamaño** en takes press-only, no aflojar filtros.  
**Verificado:** gates + resize live floors + fricción + preflight (2026-08-10).  
**Entorno real:** [`REAL_ENV_READY.md`](REAL_ENV_READY.md) → `python3 -m polymarket.research.local_lab.real_env_ready --scale high`

| Escala | Depósito | $/trade | Semana limpia | Semana conservadora* | Mes limpio | Mes conservador* |
|--------|----------|---------|---------------|----------------------|------------|------------------|
| micro | $25 | ~$5 | ~$41 | ~$24 | ~$178 | ~$101 |
| standard | $50 | ~$12 | ~$99 | ~$57 | ~$426 | ~$243 |
| **high** | **$100** | **~$25** | **~$207** | **~$118** | **~$888** | **~$506** |
| aggressive | $200 | ~$50 | ~$414 | ~$236 | ~$1776 | ~$1012 |

\*Conservador = haircut ~0.57 por slip/fee/fill hostil + floors CLOB (medido @$25 budget).  
\*Hoy a menudo **$0** si no hay basket press ≤0.50 (ahora accepted_n=0).

## Verificación de funcionamiento (escalado)

| Check | Resultado |
|-------|-----------|
| DNA press-only alineado | PASS |
| Cap sin `POLY_LADDER_HIGH_INCOME` | **$5** (fallback seguro) |
| Cap con env | **$50** |
| 11/11 takes resizen a budget $25 con floors | PASS |
| Compound $100 @ $25/trade (limpio) | ~$205/sem equiv · end ~$1008 |
| Hostile @ $25 | WR 90.9% · ~$118/sem |
| Proyección high ≈ compound limpio | ~$207 vs ~$205 |
| Preflight live | bloquea por geoblock US + balance ~$3.45 + sin edge |

## Qué NO hacer

- Meter tier `select` → WR ~77%
- Subir basket a 0.60 “para operar hoy” → peor calidad
- Forzar Shanghai sin underdispersion

## Comandos

```bash
# Proyecciones verificadas (clean + conservative)
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
