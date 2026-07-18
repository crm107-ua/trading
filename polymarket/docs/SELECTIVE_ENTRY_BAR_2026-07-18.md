# Grind NIM Selective — listón de entrada alto

**Fecha:** 2026-07-18  
**Idea:** subir WR entrando menos (mayor `min_edge` / `min_z`).  
**Live:** no armado (`POLY_LIVE_DRY_RUN=1`).

## Parámetros (v2)

| Param | Base (`grind_nim_best`) | Selective v2 |
|-------|-------------------------|--------------|
| `min_edge` | 0.026 | **0.031** |
| `min_z` | 0.85 | **1.0** |
| `max_abs_edge` | 0.09 | **0.085** |
| mid | 0.28–0.72 | **0.28–0.72** (igual) |
| lock / max_loss | 0.10 | 0.10 |

## Resultados feeds reales @10 € (6×5)

### v1 (mid 0.32–0.68) — rechazada
`WR 25%` (1W/3L), total **−0.18**, worst −0.10  
Log: `selective10_20260718_193617.log`

### v2 (edge/z altos, mid base) — en validación
Ver artefacto `iterate_*` / log `selective10_v2_*`.

## Entorno “real” comprobado (sin dinero)
- Paper con libros Polymarket + BTC spot (Binance.US fallback)
- `dry_e2e_batch` checklist OK
- `live_maker` **DRY** contra CLOB (`ARMED=1` + `DRY_RUN=1`): conectó, balance leído, **0 órdenes reales**
- `POLY_LIVE_ARMED` de vuelta a 0 en `.env` local tras pruebas dry

## Criterio de éxito
WR traded ≥ **75%**, sesiones traded ≥ 3, total > 0 @10 €.  
Solo entonces promover a `grind_nim_best`.
