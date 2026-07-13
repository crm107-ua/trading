# freqtrade-quant-lab

Laboratorio cuantitativo profesional construido sobre [Freqtrade](https://www.freqtrade.io/).

Este repositorio **no reimplementa** el motor de trading. Freqtrade ejecuta backtests, hyperopt y (en fases futuras) dry-run y live. Este proyecto aporta:

- **Estrategias** con lógica de régimen, riesgo y protecciones compartidas.
- **Guardas anti-lookahead** que detectan señales que miran al futuro.
- **Pipeline de validación** (Fase 4) con split IS/OOS, múltiples semillas, walk-forward y veredicto numérico.
- **Scripts operativos** para repetir el mismo flujo en Windows y Linux.
- **Tests** unitarios (rápidos) e integración (Docker).

El objetivo es llevar una estrategia desde la idea hasta operación real con **disciplina reproducible**, no con intuición post-hoc.

---

## Tabla de contenidos

1. [Aviso de riesgo](#1-aviso-de-riesgo)
2. [Conceptos clave](#2-conceptos-clave)
3. [Arquitectura del repositorio](#3-arquitectura-del-repositorio)
4. [Las cinco estrategias](#4-las-cinco-estrategias)
5. [Fases del proyecto y flujo de trabajo](#5-fases-del-proyecto-y-flujo-de-trabajo)
6. [Instalación paso a paso (primera vez)](#6-instalación-paso-a-paso-primera-vez)
7. [Flujo diario: backtest con guardas](#7-flujo-diario-backtest-con-guardas)
8. [Flujo Fase 4: validación IS/OOS](#8-flujo-fase-4-validación-isoos)
9. [Calibración de umbrales (MeanRevBB)](#9-calibración-de-umbrales-meanrevbb)
10. [Comandos de referencia](#10-comandos-de-referencia)
11. [Monitorear un hyperopt en curso](#11-monitorear-un-hyperopt-en-curso)
12. [Seguridad y secretos](#12-seguridad-y-secretos)
13. [Tests y calidad](#13-tests-y-calidad)
14. [Mapa de documentación](#14-mapa-de-documentación)
15. [Solución de problemas](#15-solución-de-problemas)

---

## 1. Aviso de riesgo

**El trading algorítmico conlleva riesgo de pérdida total del capital.**

- Los resultados de backtest e hyperopt **no garantizan** rendimiento futuro.
- Los fixtures sintéticos están diseñados para **disparar señales**, no para estimar rentabilidad.
- Este software es con fines educativos y de investigación; **no constituye asesoramiento financiero**.
- Opera solo con capital que puedas permitirte perder por completo.

---

## 2. Conceptos clave

### ¿Qué hace Freqtrade aquí?

Freqtrade es el **motor**: carga datos OHLCV, calcula indicadores, simula órdenes, ejecuta hyperopt y (más adelante) opera en dry-run/live. Todo corre en **Docker** con una imagen pinneada por digest SHA256 para reproducibilidad.

### ¿Qué aporta este laboratorio?

| Capa | Ubicación | Función |
|------|-----------|---------|
| **Estrategias** | `user_data/strategies/` | Señales de entrada/salida por régimen de mercado |
| **Núcleo cuant** | `quant_core.py`, `_base.py` | Régimen BTC, stoploss ATR, sizing, confirmación de entrada |
| **Herramientas** | `user_data/tools/` | Comprobaciones de señales, régimen, DCA, pickle hyperopt |
| **Pipeline** | `pipeline/` | Orquesta validación IS/OOS sin importar Freqtrade en el host |
| **Scripts** | `scripts/` | Atajos para backtest, descarga, validación, diagnóstico |
| **Tests** | `tests/` | Lógica pura + smoke Docker |

### Régimen de mercado (BULL / BEAR / RANGE)

Todas las estrategias cuant usan BTC/USDT en **4h** como referencia de régimen:

- **BULL**: precio por encima de EMA200 y ADX fuerte → favorece tendencia.
- **BEAR**: precio por debajo de EMA200 y ADX fuerte → bloquea longs (por defecto).
- **RANGE**: ADX bajo → favorece mean-reversion y grid.

Cada estrategia solo opera en el régimen para el que fue diseñada.

### Guardas anti-lookahead

Antes de confiar en un backtest, el pipeline verifica que las señales **no cambien** si truncas datos futuros. Sin esto, un backtest puede mostrar beneficios irreales.

Ver [docs/OPERATIONS.md](docs/OPERATIONS.md) para el detalle técnico.

### Validación IS/OOS (Fase 4)

No basta con un backtest bonito en todo el histórico. El pipeline:

1. Divide el tiempo en **In-Sample (70%)** y **Out-of-Sample (30%)** con fechas fijas.
2. Optimiza parámetros solo en IS (hyperopt con varias **semillas**).
3. Evalúa en OOS con parámetros congelados.
4. Opcionalmente ejecuta **walk-forward** (ventanas rodantes).
5. Emite un **veredicto**: `ROBUSTA`, `DUDOSA` o `SOBREAJUSTADA`.

---

## 3. Arquitectura del repositorio

```
trading/
├── docker-compose.yml          # Freqtrade pinneado + FreqUI
├── .env                        # Secretos (exchange, API, Telegram)
├── pyproject.toml              # Dependencias Python del pipeline local
│
├── user_data/
│   ├── config/                 # base.json, backtest.json, dryrun.json…
│   ├── strategies/             # TrendRider, MeanRevBB, BreakoutVol…
│   ├── hyperopts/              # QuantRobustLoss (función de hyperopt)
│   ├── data/binance/           # OHLCV reales (Git LFS)
│   ├── fixtures/data/          # Datos sintéticos para CI (BULL+RANGE)
│   ├── tools/                  # Guards programáticos (signal, régimen…)
│   ├── hyperopt_results/       # Resultados hyperopt (Git LFS)
│   └── validation_reports/     # report.json por estrategia y run
│
├── pipeline/                   # Orquestador Fase 4 (host → Docker)
│   ├── run_validation.py       # CLI principal
│   ├── run_lock.py             # Lockfile anti-colisión
│   ├── verdict_engine.py       # Veredicto numérico
│   ├── walk_forward.py         # Ventanas WF + WFE
│   └── params_manager.py       # Limpieza/archivo de <Estrategia>.json
│
├── scripts/                    # Entrada operativa (PowerShell + bash)
├── tests/                      # Unitarios + integración Docker
├── docs/                       # Guías detalladas por tema
└── risk/                       # Monitor y go-live (Fases 5–6, scaffold)
```

### Dos mundos de datos

| Datos | Ruta | Uso |
|-------|------|-----|
| **Fixtures** | `tests/fixtures/data/` y `user_data/fixtures/data/` | CI, smoke rápido, guards (~3 meses sintéticos) |
| **Reales** | `user_data/data/binance/` | Hyperopt, validación full, descarga 2021→hoy |

**No copies fixtures a `user_data/data`.** Son conjuntos distintos con propósitos distintos.

### Host vs Docker

El pipeline en `pipeline/` corre en **Windows/Linux local** y solo lanza `docker compose run …`. No importa `talib` ni `freqtrade` en el host. Los indicadores y estrategias se ejecutan **dentro del contenedor**.

---

## 4. Las cinco estrategias

Todas heredan de `QuantBaseStrategy` (`_base.py`): régimen BTC, stoploss ATR, sizing 1%, protecciones, filtro de spread (solo live/dry-run).

| Estrategia | Régimen | Idea | Timeframe típico |
|------------|---------|------|------------------|
| **TrendRider** | BULL | Sigue tendencia alineada con BTC | 1h |
| **MeanRevBB** | RANGE | Mean-reversion con Bollinger + RSI | 15m |
| **BreakoutVol** | BULL | Ruptura de rango con volumen | 1h |
| **RegimeSwitcher** | BULL+RANGE | Alterna rama trend y mean-rev por tag | 1h |
| **GridDCA** | BULL+RANGE | DCA en grid con presupuesto por ciclo | 15m |

Estrategias auxiliares para tests:

- `SmokeTestStrategy` — mínima, para CI.
- `GridDCAFixture` / `RegimeSwitcherWideStop` — variantes para tests de integración.

Documentación por estrategia: [docs/STRATEGY_GUIDE.md](docs/STRATEGY_GUIDE.md), [docs/REGIME_SWITCHER.md](docs/REGIME_SWITCHER.md), [docs/GRID_DCA.md](docs/GRID_DCA.md).

---

## 5. Fases del proyecto y flujo de trabajo

El laboratorio se construye en fases. Cada fase añade una capa de confianza.

```
  Idea de estrategia
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │ Fase 1–2: Entorno + QuantBaseStrategy + tests unitarios │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │ Fase 3: Implementar estrategia + guards (backtest_all)  │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │ Fase 4: run_validation full → report.json + veredicto   │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │ Fase 5–6: Dry-run, monitor, go-live (pendiente)         │
  └─────────────────────────────────────────────────────────┘
```

| Fase | Estado | Hito | Documentación |
|------|--------|------|---------------|
| 1 | ✅ | Docker + configs + primer backtest | [SETUP.md](docs/SETUP.md) |
| 2 | ✅ | QuantBaseStrategy + tests unitarios | [STRATEGY_GUIDE.md](docs/STRATEGY_GUIDE.md) |
| 3 | ✅ | 5 estrategias + guards anti-lookahead | [OPERATIONS.md](docs/OPERATIONS.md) |
| 4 | ✅ | Pipeline IS/OOS, semillas, walk-forward, veredicto | [VALIDATION.md](docs/VALIDATION.md) |
| 5 | 🔲 | Dry-run gap + monitor de riesgo | `risk/` |
| 6 | 🔲 | Go-live con confirmación explícita | — |

### Flujo recomendado para una estrategia nueva

1. Implementar heredando `QuantBaseStrategy`.
2. Tests unitarios de lógica pura (`quant_core`, máscaras de señal).
3. `pwsh scripts/backtest_all.ps1 MiEstrategia` — debe salir en verde.
4. `python -m pytest tests/ -m "not integration"` — unitarios.
5. `pwsh scripts/run_integration_tests.ps1` — integración Docker (pre-batch o nocturno).
6. `python -m pipeline.run_validation MiEstrategia --profile smoke --skip-hyperopt` — fontanería Fase 4.
7. `python -m pipeline.run_validation MiEstrategia --profile full` — validación concluyente (horas de CPU).

---

## 6. Instalación paso a paso (primera vez)

### Requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/Mac) o Docker Engine + Compose (Linux)
- Git (+ Git LFS para clonar datos e hyperopt)
- 4 GB RAM libres mínimo; validación full requiere muchas horas de CPU

### Paso 1 — Clonar el repositorio

```bash
git clone git@github.com:crm107-ua/trading.git
cd trading
git lfs pull   # descarga user_data/data y hyperopt_results
```

### Paso 2 — Configurar secretos

```bash
cp .env.example .env
```

Edita `.env`. Para **solo backtesting** las claves de exchange pueden quedar vacías.

| Variable | Para qué sirve |
|----------|----------------|
| `FREQTRADE__EXCHANGE__KEY/SECRET` | Binance (sin permiso de retiro) |
| `FREQTRADE__API_SERVER__PASSWORD` | FreqUI / API REST |
| `FREQTRADE__TELEGRAM__*` | Alertas (opcional) |
| `STRATEGY` | Estrategia en dry-run (`SmokeTestStrategy` por defecto) |

### Paso 3 — Levantar Docker

```bash
docker compose pull
docker compose up -d
```

- **FreqUI**: http://localhost:3001
- **API REST**: http://localhost:8080
- El bot arranca en **dry-run** (simulado, sin dinero real).

### Paso 4 — Descargar datos históricos (si no vienen con LFS)

```powershell
# Windows
pwsh scripts/download_data.ps1

# Linux/Mac
./scripts/download_data.sh
```

Descarga desde **2021-01-01** hasta hoy: pares BTC, ETH, BNB, SOL, XRP en `1h`, `15m`, `4h`. No requiere API keys para OHLCV públicos.

### Paso 5 — Primer backtest con guardas

```powershell
pwsh scripts/backtest_all.ps1 SmokeTestStrategy
```

Si termina con `==> Pipeline completado`, el entorno funciona.

### Paso 6 — Entorno Python local (opcional, para pipeline y tests)

```bash
pip install -e ".[dev]"
# o con uv:
uv sync --extra dev
```

---

## 7. Flujo diario: backtest con guardas

`scripts/backtest_all.ps1` (o `.sh`) ejecuta **en orden** las comprobaciones antes del backtest final:

| Paso | Herramienta | Qué valida | ¿Bloquea? |
|------|-------------|------------|-----------|
| 1 | `regime_variety_check.py` | Régimen BTC no constante en fixtures | Sí |
| 2 | `signal_truncation_check.py` | Señales idénticas al truncar futuro | Sí |
| 3 | `recursive-analysis` | Indicadores convergen con warmup | Sí |
| 4 | `lookahead-analysis` | Reproducibilidad de trades | Advisory |
| 5 | `backtesting` | Smoke de ejecución | Sí |

```powershell
# Fixtures (rápido, ~1 min)
pwsh scripts/backtest_all.ps1 TrendRider

# Datos reales (más lento)
pwsh scripts/backtest_all.ps1 TrendRider -RealData
```

**Importante:** los números de PnL en fixtures (p. ej. TrendRider +64% en ventana corta) **no son estimación de rentabilidad** — solo confirman que el motor dispara señales.

Guards individuales:

```powershell
pwsh scripts/signal_check.ps1 MeanRevBB
pwsh scripts/recursive_check.ps1 MeanRevBB
pwsh scripts/lookahead_check.ps1 MeanRevBB
```

---

## 8. Flujo Fase 4: validación IS/OOS

### ¿Qué hace `run_validation`?

```powershell
python -m pipeline.run_validation <Estrategia> --profile smoke|full [opciones]
```

Secuencia interna (perfil `full`):

```
1. Adquirir lock (.run_lock.json) — bloquea otras herramientas
2. Calcular split IS/OOS 70/30 con fechas absolutas
3. Baseline OOS con parámetros por defecto (sin hyperopt)
4. Por cada semilla (42, 123, 456):
   a. Limpiar <Estrategia>.json
   b. Hyperopt en IS (300 epochs, -j 1)
   c. Archivar params
   d. Backtest IS y OOS con params optimizados
   e. Guardar checkpoint.json (permite reanudar)
5. Walk-forward (ventanas 12m train / 3m test) si perfil full
6. Calcular veredicto (ROBUSTA / DUDOSA / SOBREAJUSTADA)
7. Escribir report.json
8. Liberar lock
```

### Perfiles

| Perfil | Epochs | Semillas | Walk-forward | Uso |
|--------|--------|----------|--------------|-----|
| `smoke` | 30 | 1 | No | CI, comprobar fontanería (~minutos) |
| `full` | 300 | 3 | Sí | Validación concluyente (muchas horas) |

### Ejemplos

```powershell
# Fontanería sin hyperopt (~2 min)
python -m pipeline.run_validation GridDCA --profile smoke --skip-hyperopt

# Validación completa (horas → día+)
python -m pipeline.run_validation MeanRevBB --profile full

# Reanudar tras interrupción
python -m pipeline.run_validation MeanRevBB --profile full --resume-run-id 20260709_115749
```

### Salida

```
user_data/validation_reports/<Estrategia>/<run_id>/
├── report.json           # Métricas, split, veredicto, metadata Docker
├── checkpoint.json       # Semillas completadas (para --resume-run-id)
├── baseline_oos.zip      # Backtest OOS con defaults
├── params/               # JSON archivados por semilla
└── hyperopt_checkpoints/ # Copia de hyperopt_results por semilla
```

### Lock y colisiones

```powershell
python -m pipeline.run_lock check
# OK: sin lock activo
# LOCKED: hay un run_validation en curso — no tocar user_data/
```

**Regla de oro:** mientras un `full` corre, no ejecutes otras herramientas que toquen `user_data/` (diagnósticos, otro `run_validation`, etc.).

### Batch de las 5 estrategias

Solo **después** de calibrar umbrales con MeanRevBB:

```powershell
pwsh scripts/run_validation_batch.ps1
# o una sola:
pwsh scripts/run_validation_batch.ps1 -Strategy TrendRider
```

---

## 9. Calibración de umbrales (MeanRevBB)

MeanRevBB no es la estrategia “estrella” — es el **termómetro** del motor de veredicto. Se ejecuta primero en `full`; sus métricas calibran los umbrales antes del batch de las otras cuatro.

**Leer antes del reporte:** [docs/calibration_protocol.md](docs/calibration_protocol.md)

### Orden de lectura del `report.json`

1. **Métricas primero** (sin mirar el veredicto):
   - Sharpe IS/OOS por semilla
   - Degradación IS→OOS (semilla 42 es primaria)
   - PnL OOS
   - Walk-forward efficiency (WFE)
   - `max_param_divergence`
   - Distribución de regímenes OOS
   - `config_merged_sha256`, `hyperopt_job_workers`
2. **Veredicto y `reasons` al final**

### Decisión

| Veredicto | Acción |
|-----------|--------|
| ROBUSTA | Endurecer **una** frontera en `verdict_engine.py`, re-evaluar, congelar en commit |
| DUDOSA / SOBREAJUSTADA | Congelar umbrales tal cual — el control funcionó |
| DUDOSA marginal | Resistir la tentación de mover umbrales |

Luego: batch de TrendRider, BreakoutVol, RegimeSwitcher, GridDCA.

---

## 10. Comandos de referencia

### Docker y datos

| Comando | Descripción |
|---------|-------------|
| `docker compose up -d` | Bot dry-run + FreqUI |
| `docker compose logs freqtrade --tail 50` | Logs del bot |
| `pwsh scripts/download_data.ps1` | Descarga OHLCV 2021→hoy |

### Backtest y guards

| Comando | Descripción |
|---------|-------------|
| `pwsh scripts/backtest_all.ps1 <Estrategia>` | Pipeline completo con guards |
| `pwsh scripts/signal_check.ps1 <Estrategia>` | Solo truncación de señales |
| `pwsh scripts/recursive_check.ps1 <Estrategia>` | Solo recursive-analysis |

### Validación Fase 4

| Comando | Descripción |
|---------|-------------|
| `python -m pipeline.run_validation <S> --profile full` | Validación concluyente |
| `python -m pipeline.run_validation <S> --profile smoke --skip-hyperopt` | Smoke rápido |
| `python -m pipeline.run_lock check` | ¿Hay run activo? |
| `pwsh scripts/run_validation_batch.ps1` | Batch post-calibración |

### Tests

| Comando | Descripción |
|---------|-------------|
| `python -m pytest tests/ -m "not integration" -v` | Unitarios (~10 s) |
| `pwsh scripts/run_integration_tests.ps1` | Integración Docker (~5 min) |

### Diagnóstico hyperopt (solo sin run activo)

| Comando | Descripción |
|---------|-------------|
| `pwsh scripts/probe_vanilla_hyperopt_parallel.ps1` | ¿Funciona `-j 2` en vainilla vs lab? |
| `pwsh scripts/probe_hyperopt_bisect.ps1` | Bisect config vs user_data |

---

## 11. Monitorear un hyperopt en curso

No hay barra de progreso integrada. La fuente fiable es el archivo `.fthypt`:

```powershell
cd c:\ruta\al\trading
$f = Get-ChildItem user_data\hyperopt_results\strategy_MeanRevBB_*.fthypt |
     Sort-Object LastWriteTime -Descending | Select-Object -First 1
$n = (Get-Content $f.FullName | Measure-Object -Line).Lines
Write-Host "seed activa: $n / 300 ($([math]::Round(100*$n/300,1))%)"
```

Vigilante cada 5 minutos:

```powershell
while ($true) {
  $f = Get-ChildItem user_data\hyperopt_results\strategy_MeanRevBB_*.fthypt |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
  $n = (Get-Content $f.FullName | Measure-Object -Line).Lines
  Write-Host "$(Get-Date -Format HH:mm:ss)  $n/300 ($([math]::Round(100*$n/300,1))%)"
  Start-Sleep -Seconds 300
}
```

Si el contador no sube 15–20 min con el PID vivo → revisar `docker logs <contenedor>`.

### Tiempos realistas (perfil full)

- ~1–1.5 min/epoch con `-j 1` → **~6 h por semilla** de 300 epochs.
- 3 semillas + backtests IS/OOS + walk-forward → **>24 h** es normal.
- **Evita suspender el PC** durante el batch (`powercfg /change standby-timeout-ac 0`).

### GPU

Este hyperopt usa **CPU** (pandas + TA-Lib). La GPU no acelera el batch salvo que uses FreqAI (no está en este repo). Comprueba con `nvidia-smi` — si GPU-Util es 0%, es esperado.

---

## 12. Seguridad y secretos

| Regla | Detalle |
|-------|---------|
| Dry-run por defecto | `dry_run: true` en configs |
| Secretos en `.env` | Nunca en JSON versionado |
| Claves Binance | Sin permiso de retiro + whitelist IP |
| Live separado | `user_data/config/live.json` (gitignored) + confirmación Fase 6 |
| Repo público | Si `.env` tiene claves reales, **rótalas** |

### Imagen Docker pinneada

`docker-compose.yml` fija el digest SHA256 de Freqtrade. El mismo digest queda en `report.json` → `docker_runtime`. No uses `:stable` sin pin — el tag se mueve y rompe reproducibilidad.

---

## 13. Tests y calidad

### Pirámide de tests

```
                    ┌─────────────────────┐
                    │  Integración Docker │  ~26 tests, ~5 min
                    │  (guards end-to-end)│
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Unitarios         │  ~88 tests, ~10 s
                    │   (lógica pura)     │
                    └─────────────────────┘
```

```powershell
# Desarrollo rápido (cada cambio de código)
python -m pytest tests/ -m "not integration" -v

# Pre-batch o nocturno (detecta contratos CLI rotos)
pwsh scripts/run_integration_tests.ps1

# Lint
ruff check pipeline tests
```

Los tests de integración deben invocar las herramientas **igual que** `backtest_all.ps1` (sin `--datadir` en tools programáticos — lo fija `fixture_config` internamente).

---

## 14. Mapa de documentación

| Documento | Contenido |
|-----------|-----------|
| [docs/SETUP.md](docs/SETUP.md) | Instalación detallada, pairlists, protecciones |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Guards anti-lookahead, callbacks causales |
| [docs/STRATEGY_GUIDE.md](docs/STRATEGY_GUIDE.md) | QuantBaseStrategy, parámetros, correlación |
| [docs/VALIDATION.md](docs/VALIDATION.md) | Pipeline Fase 4, lock, hyperopt, LFS |
| [docs/calibration_protocol.md](docs/calibration_protocol.md) | Protocolo pre-registrado de umbrales |
| [docs/REGIME_SWITCHER.md](docs/REGIME_SWITCHER.md) | Dispatch por enter_tag |
| [docs/GRID_DCA.md](docs/GRID_DCA.md) | Presupuesto DCA, capas, régimen |
| [docs/HYPEROPT_PARALLEL_BISECT.md](docs/HYPEROPT_PARALLEL_BISECT.md) | Bisect `-j 2` y pickle |
| [polymarket/README.md](polymarket/README.md) | **Rama Polymarket Lab** (#15) — prediction markets, separado de Freqtrade |
| [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) | Cierre Binance + nota rama Polymarket |

---

## 15. Solución de problemas

| Síntoma | Qué hacer |
|---------|-----------|
| `env file .env not found` | `cp .env.example .env` |
| Backtest 0 trades (fixtures) | `python tests/fixtures/generate_data.py` |
| Backtest 0 trades (reales) | Ampliar timerange o `download_data.ps1` |
| `LOCKED` al lanzar validación | Esperar al run activo o verificar PID en `.run_lock.json` |
| Hyperopt atascado | Contador `.fthypt` sin subir 15+ min → `docker logs` |
| Contenedor `unhealthy` en hyperopt | Benigno — no hay api_server en modo hyperopt |
| `PicklingError` con `-j 2` | Usar `-j 1` (default) o ver bisect en docs |
| Archivos >100 MB en git | Usar `git lfs pull` tras clonar |

---

## Desarrollo local

```bash
pip install -e ".[dev]"
python -m pytest tests/ -m "not integration" -v
ruff check pipeline tests
```

Estructura Python del paquete: `pipeline/` y `risk/` (ver `pyproject.toml`).

---

## Licencia y responsabilidad

Uso bajo tu propia responsabilidad. Consulta el [aviso de riesgo](#1-aviso-de-riesgo) antes de operar con dinero real.
