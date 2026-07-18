# Grind NIM Selective — listón de entrada alto

**Fecha:** 2026-07-18  
**Estado:** **PROMOVIDO** a `grind_nim_best` tras validación feeds reales @10 €  
**Idea:** subir WR entrando menos (mayor `min_edge` / `min_z`), sin estrechar mid.  
**Live dinero real:** aún no (`POLY_LIVE_DRY_RUN=1` / no armar sin dry-E2E largo).

## Parámetros finales (v2 → campeón)

| Param | Base antiguo | Selective v2 / BEST |
|-------|--------------|---------------------|
| `min_edge` | 0.026 | **0.031** |
| `min_z` | 0.85 | **1.0** |
| `max_abs_edge` | 0.09 | **0.085** |
| mid | 0.28–0.72 | **0.28–0.72** |
| lock / max_loss | 0.10 | 0.10 |

## Resultados @10 € · 6×5 min · feeds reales

### v1 mid 0.32–0.68 — rechazada
WR **25%** (1W/3L), total −0.18, worst −0.10  
Log: `selective10_20260718_193617.log`

### v2 edge/z altos + mid base — **CAMPEÓN**
| Sesión | Net |
|--------|-----|
| 1 | **+0.23** |
| 2 | **+0.22** |
| 3 | 0 (starve) |
| 4 | **+0.07** |
| 5 | **+0.12** |
| 6 | **+0.22** |

- WR traded = **100%** (5W / 0L)  
- Total paper = **+0.86 EUR**  
- no_red = true · wr75 = true · grind = true  
- Artefacto: `iterate_20260718_203740.json`  
- Log: `selective10_v2_20260718_200715.log`

**Vs expectativas:** supera el umbral WR≥75% y el baseline reval @10€ (WR 50% / push 67%).

## Entorno real comprobado (sin órdenes on-chain)
- Paper Polymarket CLOB books + BTC spot (Binance.US fallback)
- `dry_e2e_batch` checklist OK
- `live_maker` DRY (`ARMED=1` + `DRY_RUN=1`): CLOB/balance OK (~10.9 pUSD), **0 órdenes reales**
- `.env` local: `POLY_LIVE_ARMED=0` tras las pruebas

## Archivos
- `config/maker_demo_grind_nim_best.json` (promovido)
- `config/maker_demo_grind_nim_selective.json` (alias DNA)
- `config/maker_demo_grind_nim_selective_micro_live.json` (prep dry)
