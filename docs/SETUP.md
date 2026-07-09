# Guía de instalación — Fase 1

Objetivo: tener el entorno funcionando y ejecutar tu **primer backtest en menos de 15 minutos** (asumiendo Docker instalado y conexión a internet para descargar la imagen y datos).

## Requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/Mac) o Docker Engine + Compose (Linux)
- 4 GB RAM libres mínimo
- Git

Opcional para desarrollo local de scripts Python 3.11+:
- [uv](https://docs.astral.sh/uv/) o Poetry

## 1. Configurar secretos

```bash
cp .env.example .env
```

Edita `.env`. Para **solo backtesting** no necesitas claves reales de exchange; deja las variables de exchange vacías. Para dry-run/live necesitarás:

| Variable | Descripción |
|----------|-------------|
| `FREQTRADE__EXCHANGE__KEY` | API key Binance (sin retiro) |
| `FREQTRADE__EXCHANGE__SECRET` | API secret |
| `FREQTRADE__API_SERVER__PASSWORD` | Contraseña FreqUI / API |
| `FREQTRADE__API_SERVER__JWT_SECRET_KEY` | Secreto JWT (string aleatorio largo) |
| `FREQTRADE__TELEGRAM__TOKEN` | Bot token (opcional en Fase 1) |
| `FREQTRADE__TELEGRAM__CHAT_ID` | Chat ID Telegram |

**Nunca** subas `.env` al repositorio.

## 2. Levantar el bot (dry-run)

```bash
docker compose pull
docker compose up -d
```

Verifica:

```bash
docker compose ps
docker compose logs freqtrade --tail 20
```

- **FreqUI**: http://localhost:3001 (conecta a API en `http://localhost:8080`)
- El bot arranca en **dry-run** con `SmokeTestStrategy` por defecto.

## 3. Descargar datos históricos

```bash
# Linux / Mac / Git Bash
chmod +x scripts/*.sh
./scripts/download_data.sh

# Windows PowerShell
pwsh scripts/download_data.ps1
```

Por defecto descarga desde **2021-01-01** hasta hoy, timeframes `1h`, `15m`, `4h`, y 5 pares líquidos.

**No requiere API keys** para OHLCV públicos de Binance; las variables de exchange en `.env` pueden quedar vacías.

Tras descargar, validar con el pipeline completo:

```bash
./scripts/backtest_all.sh TrendRider
./scripts/signal_check.sh TrendRider
```

Los datos reales van a `user_data/data/binance/` (separados de los fixtures de CI en `tests/fixtures/data/`). CI y `backtest_all` para estrategias cuant usan `user_data/config/backtest_fixtures.json` (`datadir: tests/fixtures/data`). **No copiar fixtures a `user_data/data`.**

`download_data` usa `--erase` por defecto (descarga limpia). Solo `PREPEND=1` para extender sin borrar.

Variables opcionales:

```bash
TIMERANGE=20240101-20241201 ./scripts/download_data.sh
```

## 4. Primer backtest

```bash
./scripts/backtest_all.sh SmokeTestStrategy
# Timerange custom:
TIMERANGE=20240101-20240601 ./scripts/backtest_all.sh SmokeTestStrategy
```

Los resultados se guardan en `user_data/backtest_results/`.

## 5. Tests locales

```bash
# Generar fixtures (sin red) — incluye ventanas BULL y RANGE para CI
uv run python tests/fixtures/generate_data.py

# Verificar etiquetas de régimen en fixtures
uv run pytest tests/test_fixture_regimes.py -v

# Tests unitarios (sin Docker)
uv run pytest tests/ -m "not integration" -v

# Smoke-test con Docker (integración)
uv run pytest tests/test_smoke_backtest.py -m integration -v
```

## Configuración: filtros de pairlist

La config `base.json` usa una cadena de filtros para seleccionar pares líquidos y evitar traps:

| Filtro | Propósito |
|--------|-----------|
| **VolumePairList** | Top 40 por volumen USDT — liquidez y spreads razonables |
| **AgeFilter** (30 días) | Evita listings recientes sin historial estable |
| **PrecisionFilter** | Respeta precisiones mínimas del exchange |
| **PriceFilter** | Excluye pares con precio extremadamente bajo (manipulación) |
| **SpreadFilter** (0.5%) | Rechaza pares con spread ancho en tiempo real |
| **RangeStabilityFilter** | Filtra pares en movimiento errático extremo |
| **VolatilityFilter** | Evita volatilidad fuera de rango operativo |

En **backtest** se usa `StaticPairList` (ver `backtest.json`) porque la pairlist dinámica requiere datos de mercado en vivo.

## Protecciones del bot

Desde Freqtrade 2026 las protecciones se definen en la **estrategia** (`@property protections`), no en `base.json`. En Fase 2 se centralizan en `QuantBaseStrategy`. Criterios:

- **StoplossGuard**: 4 stops en 48 velas → pausa 24h
- **MaxDrawdown**: 10% en 7 días → pausa 48h
- **CooldownPeriod**: 2 velas entre trades
- **LowProfitPairs**: Pausa pares con bajo rendimiento reciente

## Solución de problemas

| Problema | Solución |
|----------|----------|
| `env file .env not found` | `cp .env.example .env` |
| Backtest sin trades (estrategias BULL/RANGE) | Regenerar fixtures: `python tests/fixtures/generate_data.py` |
| Backtest sin trades (datos reales) | Amplía `TIMERANGE` o ejecuta `scripts/download_data.ps1` |
| Puerto 8080 ocupado | Cambia el mapeo en `docker-compose.yml` |
| Telegram errors al arrancar | Desactiva en `.env` dejando token vacío y `telegram.enabled: false` en base.json temporalmente |

## Siguiente paso

Fase 3: ver `docs/STRATEGY_GUIDE.md`, `docs/OPERATIONS.md`, `docs/REGIME_SWITCHER.md`.
