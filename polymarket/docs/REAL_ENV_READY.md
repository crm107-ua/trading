# Entorno real — readiness

**Gate:** `python3 -m polymarket.research.local_lab.real_env_ready --scale high`

| Veredicto | Significado |
|-----------|-------------|
| `REAL_ENV_SYSTEM_READY` | Código/DNA/safety listos (shippable) |
| `REAL_ENV_OPERATOR_READY` | + región + fondos mínimos |
| `REAL_ENV_GO` | Puede postear ahora |
| `REAL_ENV_NOT_READY` | No operar |

## Checklist operador (máquina real)

1. Región Polymarket **permitida** (no geoblock US).
2. Depositar según escala: micro ≥$25 · **high ≥$100** · aggressive ≥$200.
3. `.env` en SAFE: `POLY_LIVE_ARMED=0` · `POLY_LIVE_DRY_RUN=1`.
4. Claves: private key + `POLYMARKET_WALLET_ADDRESS` (funder).
5. High-income:
   ```bash
   export POLY_LADDER_HIGH_INCOME=1
   export POLY_LADDER_REAL_CONFIRM=1
   ```
6. Verificar:
   ```bash
   python3 -m polymarket.research.local_lab.real_env_ready --scale high
   ```
7. Ingreso:
   ```bash
   POLY_LADDER_HIGH_INCOME=1 POLY_LADDER_REAL_CONFIRM=1 \
     python3 -m polymarket.research.local_lab.definitive_income_system \
       --scale high --income-loop --auto-execute --i-accept-real-loss YES \
       --rounds 40 --interval 180
   ```

## Safety en post real

- Doble confirm (`REAL_CONFIRM` + `--i-accept-real-loss YES`)
- High size exige `POLY_LADDER_HIGH_INCOME=1`
- Geoblock re-check justo antes de armar
- Revalidación DNA (basket/UD/pierna) en libros frescos
- Abort parcial + `cancel_all` si falla una pierna
- Siempre restaura `ARMED=0` / `DRY_RUN=1`

## Expectativas (high)

Semana conservadora **~$118** · limpia **~$207**. Hoy a menudo **$0** sin edge press.

Ver [`HIGH_INCOME.md`](HIGH_INCOME.md) · [`DEFINITIVE_INCOME_SYSTEM.md`](DEFINITIVE_INCOME_SYSTEM.md)
