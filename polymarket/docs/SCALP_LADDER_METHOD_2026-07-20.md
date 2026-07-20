# Metodología SCALP LADDER (micro5) — 2026-07-20

## Objetivo

Ingresos **incrementales y controlados** en REAL:

1. Por jugada: pillar verde en escalones **1 / 2 / 3 / 4 USDC** (máx. 4).
2. Si no llega a +1€ (típico con 5 shares): bank temprano en **+0.08 USDC**.
3. Si pierde: **cancelar de inmediato** (tras 3s anti-ruido) y pasar a la siguiente.
4. Más **quotes/fills** que el micro5 selectivo (menos pausas, edge más bajo, hasta 4 entradas/sesión).

## Por qué 1–4€ con capital 5

- Con 5 shares, +1 USDC ≈ move de **+0.20** en el mid; +4 USDC ≈ +0.80 (techo raro).
- El early-bank (+0.08) acumula mientras el mercado no da el escalón grande.
- Al subir tamaño más adelante, los mismos escalones 1–4€ siguen siendo el techo de holding.

## Config

`polymarket/config/maker_demo_promo_pulse_micro5_scalp.json`

| Parámetro | Valor | Rol |
|-----------|-------|-----|
| `scalp_ladder_enable` | true | Activa el modo |
| `scalp_bank_ladder_usdc` | [1,2,3,4] | Escalones de take |
| `scalp_max_bank_usdc` | 4 | Techo duro |
| `scalp_early_bank_usdc` | 0.10 | Micro-verde |
| `scalp_cut_usdc` | 0.10 | Cut en rojo |
| `scalp_min_hold_cut_s` | 6 | Anti-ruido post-fill |
| `max_entry_fills` | 4 | Más jugadas/sesión |
| `pause_after_consecutive_losses` | 3 / 45s | Antes: 1 / 900s (mataba actividad) |
| `min_edge` | 0.012 | Más quotes |

## Código

- Decisión pura: `research/local_lab/scalp_ladder.py` → `decide_scalp_exit`
- Integración: `live_maker._maybe_exit` si `scalp_ladder_enable`
- Tests: `tests/test_scalp_ladder.py`, `tests/test_dust_topup_no_double.py`

## Anti-doble inventario (sesión 181122)

Bug: fill parcial ~4.99 → top-up compraba **+5 enteros** → inv≈10.

Mitigaciones en `live_maker`:
1. `_topup_dust_to_min`: solo delta; si `need < 5` → `DUST_TOPUP_SKIP` (nunca +5).
2. Salidas `scalp_*`: `FLATTEN_WAIT_SIZE` sin top-up; scalp no cut/bank hasta `inv ≥ 5`.
3. `INV_SYNC`: si CLOB ≥5 y local corto, alinear antes de vender.
4. `INV_CAP_BREACH` / `inv_cap`: halt + flatten si inv > `max_inventory_shares`.
5. `EXIT_RESTING`: si el SELL agresivo queda LIVE, **no** publicar un segundo SELL (185109: allowance 400).
6. `bal=0` con inv local → `cancel_all` + re-sync antes de `FLATTEN_WRONG_TOKEN`.

## Cómo correr REAL

```bash
python -m polymarket.research.local_lab.run_real_micro25 \
  --capital 5 --minutes 12 \
  --config maker_demo_promo_pulse_micro5_scalp.json
```

Protocolo: **1 sesión a la vez**, revisar `ok` / residual / danger antes de la siguiente.

## Criterio de validación (WR decente)

Tras ≥20 jugadas (fills cerrados) en modo scalp:

- Win rate ≥ 55% (o IC90 que cubra breakeven tras fricción).
- Mean |loss| ≤ early_bank (cuts controlados).
- Sin `unclosed_position` / residual > dust.
- No ESCALAR tamaño hasta cumplir lo anterior.
