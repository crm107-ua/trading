# Cómo queda todo para meter dinero real

> **Sistema definitivo:** [`DEFINITIVE_INCOME_SYSTEM.md`](DEFINITIVE_INCOME_SYSTEM.md)  
> Entrypoint: `python3 -m polymarket.research.local_lab.definitive_income_system`

## Foto del sistema

```
Research canónico
  └─ weather_ladder_final_longterm  →  LONG_TERM_ROBUST

Sistema definitivo (orquestador)
  └─ definitive_income_system  →  CERTIFIED / OPERABLE / GO

Manga real
  └─ weather_ladder_definitive_real  →  ≤$5/sesión · press-only · hold resolución
```

| Capa | Archivo | Dinero |
|------|---------|--------|
| Final research | `config/weather_ladder_final_longterm.json` | paper |
| Ultra-real sim | `config/weather_ladder_ultra_real_sim.json` | paper+friction |
| Micro dry | `config/weather_ladder_micro_dry.json` | $0 (would_post) |
| **Definitive real** | `config/weather_ladder_definitive_real.json` | **≤ $5 / sesión** |
| Micro real (alias) | `config/weather_ladder_micro_real.json` | ≤ $5 |

## Flujo operativo con capital real

1. **Deposita** USDC (≥**$25** recomendado; mínimo técnico ~$2).
2. **Estado del sistema** (sin órdenes):
   ```bash
   python3 -m polymarket.research.local_lab.definitive_income_system
   ```
3. **Ingreso automático** (región permitida):
   ```bash
   POLY_LADDER_REAL_CONFIRM=1 \
     python3 -m polymarket.research.local_lab.definitive_income_system \
       --income-loop --auto-execute --i-accept-real-loss YES \
       --rounds 40 --interval 180
   ```

## Gates que deben pasar

- DNA press-only alineado (final = definitive real)
- `LONG_TERM_ROBUST` + WR80 + income-assured
- `POLY_LADDER_REAL_CONFIRM=1` + `--i-accept-real-loss YES`
- Geoblock OK · Balance ≥ notional · Cap ≤ $5 · 1 mercado
- Take press abierto (no near-miss forzado)
- Tras correr: `ARMED=0` `DRY_RUN=1`

## Qué NO se hace en real

- No grind BTC idle / copy wallets virales
- No escalar sizing paper hasta 3–5 resoluciones live verdes
- No `DRY_RUN=0` permanente en `.env`
- No operar con veredicto `DEFINITIVE_NOT_READY`
