# Cómo queda todo para meter dinero real

## Foto del sistema

```
Research / Paper (ya ganado)
  └─ Temperature Ladder v3  →  WR100% research · paper +$418 · ultra-real +$502

Dry live (ya montado)
  └─ weather_ladder_live --mode both  →  MICRO_DRY_PATH_READY

Real micro (listo, gated)
  └─ weather_ladder_real  →  preflight por defecto
       └─ --execute-real + confirmaciones  →  FAK 3 piernas · hold a resolución
```

| Capa | Archivo | Dinero |
|------|---------|--------|
| Champion | `config/weather_ladder_champion_v2.json` | paper |
| Ultra-real sim | `config/weather_ladder_ultra_real_sim.json` | paper+friction |
| Micro dry | `config/weather_ladder_micro_dry.json` | $0 (would_post) |
| **Micro real** | `config/weather_ladder_micro_real.json` | **≤ $5 / sesión** |

## Flujo operativo con capital real

1. **Deposita** USDC en la wallet Polymarket (hoy ~$3.45 → ideal **$25–50** para operar holgado con floors de 5 shares × 3 piernas).
2. **Preflight** (sin órdenes):
   ```bash
   python3 -m polymarket.research.local_lab.weather_ladder_real
   ```
3. **Espera edge** (libros baratos):
   ```bash
   python3 -m polymarket.research.local_lab.weather_ladder_live \
     --mode watch --watch-rounds 40 --watch-interval 180
   ```
4. **Ejecuta real** solo si preflight dice `can_execute_now=true`:
   ```bash
   POLY_LADDER_REAL_CONFIRM=1 \
     python3 -m polymarket.research.local_lab.weather_ladder_real \
       --execute-real --i-accept-real-loss YES
   ```
5. El bot compra las 3 piernes YES (FAK), **mantiene hasta resolución**, y deja el entorno en SAFE.

## Gates que deben pasar

- `POLY_LADDER_REAL_CONFIRM=1`
- `--i-accept-real-loss YES`
- Geoblock OK
- Balance ≥ $2 y ≥ notional del basket
- Cap sesión ≤ **$5**
- Take champion presente (no smoke, no near-miss forzado)
- 1 mercado máx / sesión
- Tras correr: `ARMED=0` `DRY_RUN=1`

## Qué NO se hace en real (aún)

- No grind BTC idle
- No copy de wallets virales
- No escalar a $150 paper sizing hasta 3–5 resoluciones live verdes
- No `DRY_RUN=0` permanente en `.env`

## Estado típico “ahora”

- Camino técnico: **listo**
- Edge abierto champion: a menudo **0** (libros caros) → watch
- Near-miss posible (ej. Shanghai basket 0.66 / EV+) → **no** se toma en real
- Primer tamaño real: **$3–5** por basket, no el bankroll entero
