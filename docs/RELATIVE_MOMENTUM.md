# RelativeMomentum — diseño y operación

Estrategia de **momentum cross-sectional**: clasificar 5 pares (BTC, ETH, BNB, SOL, XRP) por retorno acumulado en ventana diaria y mantener largos en el top-N. Rotación con histéresis y banda muerta.

## Tesis

Persistencia de momentum relativo en cripto; estructuralmente distinta de señales absolutas (TrendRider, MeanRevBB, etc.).

## Convención causal del score

En `relative_momentum_core.momentum_score`:

- Score en vela `t` usa cierres hasta `t-1` (`close.shift(1) / close.shift(1+window) - 1`).
- Ranking 1d fusionado a 1h con `merge_informative_pair(..., ffill=True)` (asof hacia atrás).
- Señal en cierre de `t`, ejecución en `t+1`.

**Zona de riesgo:** informative multi-par — obligatorio `signal_truncation_check` en verde antes de validación.

## Decisiones de diseño

| Tema | Decisión |
|------|----------|
| Histéresis | `confirm_bars` = **días** consecutivos en top-N (`rotation_entry_mask_daily`); no velas 1h |
| Banda muerta | Entra top-N; sale si `rank > exit_rank_k` (K ≥ N) |
| BEAR | Sin entradas nuevas; posiciones abiertas salen por rotación + stop ATR (sin cierre forzoso por régimen) |
| Sizing | 1% riesgo (base); `max_open_trades` en config ≥ `top_n` (1–2) |
| Hyperopt | 4 params en `space="buy"`: `momentum_window` 7–30d, `top_n` 1–2, `confirm_bars` 1–5, `exit_rank_k` 2–3 |

## Archivos

| Archivo | Rol |
|---------|-----|
| `user_data/strategies/relative_momentum_core.py` | Funciones puras |
| `user_data/strategies/RelativeMomentum.py` | Estrategia Freqtrade |
| `user_data/fixtures/screen_variants/RelativeMomentum.json` | Variantes del screen |
| `tests/fixtures/generate_relative_momentum_data.py` | Fixtures 5 pares + 1d |

## Comandos (anotados — no ejecutar validación full con lock activo)

### (a) Guards de integración — **post-lock**

Añadir `RelativeMomentum` a `scripts/backtest_all.ps1` y matrices en `tests/test_smoke_backtest.py` antes de ejecutar.

```powershell
# Fixtures RelativeMomentum (datadir dedicado)
python tests/fixtures/generate_relative_momentum_data.py

docker compose run --rm --entrypoint python freqtrade user_data/tools/regime_variety_check.py `
  --strategy RelativeMomentum --timerange 20240101-20240320 `
  --config user_data/config/base.json --config user_data/config/backtest.json `
  --config user_data/config/backtest_relative_momentum_fixtures.json

docker compose run --rm --entrypoint python freqtrade user_data/tools/signal_truncation_check.py `
  --strategy RelativeMomentum --timerange 20240101-20240320 `
  --config user_data/config/base.json --config user_data/config/backtest.json `
  --config user_data/config/backtest_relative_momentum_fixtures.json

pwsh scripts/backtest_all.ps1 -Strategy RelativeMomentum
# (tras añadir la estrategia a la matriz del script)
```

Datadir fixtures: `--datadir /freqtrade/tests/fixtures/data_relative_momentum/binance`

### (b) Screen — **permitido con lock** (un backtest secuencial)

```powershell
python user_data/tools/screen_strategy.py RelativeMomentum --fixtures --timerange 20240101-20240320
# o: pwsh scripts/screen.ps1 -Strategy RelativeMomentum -Fixtures
```

### (c) Validación full — **solo post-lock + screen/documentación**

```powershell
python -m pipeline.run_validation RelativeMomentum --profile full --adopt-partial-hyperopt
# Decisión WF batch (MeanRevBB control ya a 300/ventana): ver calibration_protocol.md
```

### Datos 1d reales (post-lock, sin --erase)

```powershell
pwsh scripts/download_1d_universe.ps1
```

## Tests unitarios (host, sin Docker)

```powershell
python -m pytest tests/test_relative_momentum_core.py tests/test_relative_momentum.py tests/test_screen_strategy.py -q
```

## Integración pendiente (archivos existentes — no tocados con lock)

- `scripts/backtest_all.ps1` / `.sh` — añadir `RelativeMomentum`
- `tests/test_smoke_backtest.py` — parametrize guards
- Opcional post-veredicto MeanRevBB: fusionar `relative_momentum_core` en `quant_core.py`
