# Live dry-run real @5/@10 (2026-07-19)

Entorno **completamente real** (CLOB Polymarket + feeds BTC + discovery de mercados),
con **0 dinero real** (`POLY_LIVE_DRY_RUN=1`).

## Cómo repetir
```bash
POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=1 POLY_LIVE_MAX_CAPITAL_USDC=10 \
  python3 -m polymarket.research.local_lab.run_live_dry_pair --minutes 5
```

## Resultado (sesión 20260719_080303)
| Capital | DNA | Verdict | Fills | Net (sim) | Órdenes reales |
|---------|-----|---------|-------|-----------|----------------|
| 5 | promo_flow_c5 | LIVE_DRY_RUN | 1 (`dry-2`) | -0.12 | 0 |
| 10 | promo_pulse_c10 | LIVE_DRY_RUN | 1 (`dry-4`) | 0.00 | 0 |

- Balance CLOB pre/post ≈ **10.93 pUSD** (sin gasto)
- Tras la prueba: `ARMED=0` `DRY_RUN=1` restaurado
- Report: `data_local/local_lab/live_dry_pair/dry_pair_latest.json`
