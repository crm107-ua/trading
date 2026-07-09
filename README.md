# freqtrade-quant-lab

Laboratorio cuantitativo profesional sobre [Freqtrade](https://www.freqtrade.io/). Este repositorio **no reimplementa** el motor de trading: aporta estrategias avanzadas, pipeline de validación, gestión de riesgo, despliegue y monitoreo para llevar estrategias desde la idea hasta operación real con disciplina.

## Aviso de riesgo

**El trading algorítmico conlleva riesgo de pérdida total del capital.** Los resultados de backtest e hyperopt **no garantizan** rendimiento futuro. Este software es con fines educativos y de investigación; **no constituye asesoramiento financiero**. Opera solo con capital que puedas permitirte perder por completo.

## Seguridad

- Modo por defecto: **`dry_run: true`** siempre.
- Paso a real: archivo separado + script con confirmación explícita (Fase 6).
- Claves API **solo** en `.env` (nunca en JSON versionado).
- Crea claves de Binance **sin permiso de retiro** y con **whitelist de IP**.

## Inicio rápido (Fase 1)

```bash
# 1. Clonar y configurar secretos
cp .env.example .env
# Editar .env con valores mínimos (pueden ser dummy para backtest)

# 2. Levantar bot en dry-run + FreqUI
docker compose up -d

# 3. Descargar datos (requiere red)
./scripts/download_data.sh          # Linux/Mac
# o: pwsh scripts/download_data.ps1  # Windows

# 4. Primer backtest
./scripts/backtest_all.sh SmokeTestStrategy
```

- FreqUI: http://localhost:3001
- API REST del bot: http://localhost:8080

Documentación detallada: [docs/SETUP.md](docs/SETUP.md)

## Estructura

```
user_data/          # Config, estrategias, datos
pipeline/           # Validación Fase 4 (`python -m pipeline.run_validation`)
risk/               # Monitor y checklist go-live (Fase 5-6)
scripts/            # Utilidades operativas
tests/              # Tests unitarios e integración
docs/               # Guías de setup, estrategias y operaciones
```

## Desarrollo

```bash
# Con uv (recomendado)
uv sync --extra dev
uv run pytest tests/ -m "not integration"
uv run ruff check .
```

## Fases del proyecto

| Fase | Estado | Hito |
|------|--------|------|
| 1 | ✅ | Docker + configs + primer backtest |
| 2 | ✅ | QuantBaseStrategy + tests unitarios |
| 3 | En curso | TrendRider, MeanRevBB, BreakoutVol, RegimeSwitcher, GridDCA ✅ |
| 4 | Pendiente | Pipeline de validación |
| 5 | Pendiente | Dry-run gap + monitor |
| 6 | Pendiente | go_live + CI + docs completas |

## Licencia

Uso bajo tu propia responsabilidad. Consulta el aviso de riesgo antes de operar con dinero real.
