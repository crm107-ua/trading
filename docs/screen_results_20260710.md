# Resultados screen — 2026-07-10

Embudo de screening **cerrado** con veredictos **FINALES** (`params_verified_all: true` en todos los reports de hoy). Criterios: `docs/screen_protocol.md` (sin calibración ex post).

## Tabla resumen

| Estrategia | Defaults bruto (USDT) | Mejor variante bruto | Fricción | Trades (mejor) | params_verified | Veredicto FINAL |
|------------|----------------------:|---------------------:|----------|---------------:|:---------------:|-----------------|
| TrendRider | −8 204.45 | −4 311.04 (`stricter_trend_filter`) | n/a (bruto ≤ 0) | 438 | sí | **DESCARTADA** |
| BreakoutVol | −9 352.07 | −8 429.93 (`selective_volume`) | n/a | 905 | sí | **DESCARTADA** |
| RegimeSwitcher | −9 839.42 | −9 524.70 (`selective_trend_branch`) | n/a | 1 343 | sí | **DESCARTADA** |
| GridDCA | −9 703.59 | −9 702.10 (`lower_dca_threshold`) | n/a | 8 839 | sí | **DESCARTADA** |
| RelativeMomentum | −9 979.72 | −9 979.72 (`defaults`) | n/a | 7 359 | sí | **DESCARTADA** |

*Bruto = `profit_gross_abs` (neto + comisiones). Fricción no aplica cuando bruto ≤ 0.*

## Mejor variante por estrategia (una línea)

| Estrategia | Variante | Por qué es la mejor del set |
|------------|----------|-----------------------------|
| TrendRider | `stricter_trend_filter` | Menor pérdida bruta (−4.3k vs −8.2k defaults); filtros ADX/RSI/volumen reducen trades de 1 053 → 438. |
| BreakoutVol | `selective_volume` | Menor pérdida bruta; breakout 30d + volumen 22 filtra señales marginales (905 trades). |
| RegimeSwitcher | `selective_trend_branch` | Menor pérdida bruta; rama trend más selectiva (ADX 28, vol 20). |
| GridDCA | `lower_dca_threshold` | Empate técnico con defaults (−9 702 vs −9 704); `pullback_plus_grid` empeora. |
| RelativeMomentum | `defaults` | Ninguna variante supera defaults en bruto; todas ~−10k con params verificados. |

## Reports finales (ruta)

| Estrategia | `run_id` | Ruta |
|------------|----------|------|
| TrendRider | `20260710_124444` | `user_data/validation_reports/screen/TrendRider/20260710_124444/` |
| BreakoutVol | `20260710_124547` | `user_data/validation_reports/screen/BreakoutVol/20260710_124547/` |
| RegimeSwitcher | `20260710_125143` | `user_data/validation_reports/screen/RegimeSwitcher/20260710_125143/` |
| GridDCA | `20260710_135605` | `user_data/validation_reports/screen/GridDCA/20260710_135605/` |
| RelativeMomentum | `20260710_145340` | `user_data/validation_reports/screen/RelativeMomentum/20260710_145340/` |

Re-screens 1–4: `--skip-defaults` + defaults reutilizados de reports provisionales del `20260710_10*`.

## Estado MeanRevBB al cierre del día

| Campo | Valor |
|-------|-------|
| Lock | **ACTIVO** — `MeanRevBB`, pid `38004`, `run_id=20260709_162954` |
| Hyperopt en curso | Semilla **456**, `strategy_MeanRevBB_2026-07-10_11-21-44.fthypt` ≈ **283/300** epochs |
| `MeanRevBB.json` | **No escrito** por screen (guard anti-lock operativo) |

## Anomalías y fixes del día

1. **Bug variantes (ayer):** Freqtrade ignora `strategy_parameters` en config; carga desde `<Estrategia>.json` con bloque `buy`/`sell` **completo**. Fix en `screen_strategy.py`: escritura JSON + verificación vía log + snapshot/restore.
2. **`atr_stop_multiplier`:** No es cargable vía `.json` ni `strategy_parameters` en Freqtrade (atributo de clase). Variantes `wider_atr_stop` **retiradas** de fixtures TrendRider/RegimeSwitcher.
3. **RelativeMomentum truncation:** 52 diffs `full=1/trunc=0` por lookahead intradía en `rotation_entry_mask_daily` → fix `shift(1)` en ranking diario; truncation **OK** tras fix.
4. **Scripts PowerShell:** `download_1d_universe.ps1` (pares como array), `signal_check.ps1` (`--entrypoint python`), `recursive_check.ps1` (`--startup-candle` repetido).
5. **Datos 1d:** 5 pares × 2 016 velas (2021-01-01 → 2026-07-09), gap máx 1 día; 1h/15m/4h intactos.
6. **Intentos fallidos RM screen:** `20260710_145007` / `145227` por JSON con comentarios `#` en fixture (corregido).
7. **Ninguna estrategia PASA** ni entra en ZONA GRIS (ningún bruto > 0).

## Fix técnico aplicado (`screen_strategy.py`)

- `build_variant_params_export()` — fusiona overrides con defaults de `IntParameter`/`DecimalParameter` del `.py`
- Guard `<Estrategia>.json` en `_pipeline_mutable_state_guard()`
- `verify_variant_params_applied()` — log Docker vs overrides solicitados
- `detect_identical_variants()` — alarma `variants_identical`
- `assert_screen_allowed()` — veto si lock activo nombra la estrategia
- `--skip-defaults` + `--prior-report`
- Tests: `tests/test_screen_strategy.py` (12), RelativeMomentum (11) — **23 passed**
