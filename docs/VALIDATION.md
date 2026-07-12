# Pipeline Fase 4 — validación

Orquestador: `python -m pipeline.run_validation <Estrategia> [opciones]`

## XSecMomentum-m35 — día del veredicto

Tras `report.json` de MeanRevBB + calibración congelada, merge de rama `validation-xsec-prep` y:

**Verificación previa (sin lock, sin Docker):**

```bash
python -m pipeline.run_validation XSecMomentum --profile full \
  --extra-config user_data/config/screen_xsec.json \
  --wf-epochs 100 \
  --dry-plan
```

**Lanzamiento:**

```bash
python -m pipeline.run_validation XSecMomentum --profile full \
  --extra-config user_data/config/screen_xsec.json \
  --wf-epochs 100 \
  --wf-min-trades 30
```

- `--extra-config` repetible; entra en `config_files` y `config_merged_sha256` del reporte.
- `--wf-epochs 100` solo afecta hyperopts de ventana WF; semillas siguen a 300 (perfil `full`).
- `--wf-min-trades 30` obligatorio para XSec: ventanas train 12m generan ~45 trades (perfil `full` usa 100 en semillas).
- Warmup WF: leído del `.py` de la estrategia (`startup_candle_count` + `timeframe`); XSecMomentum 1d → 220 velas ≈ 220 días.

## Perfiles

| Perfil | Epochs (semillas) | WF epochs | Semillas | Walk-forward | min_trades |
|--------|-------------------|-----------|----------|--------------|------------|
| `smoke` | 30 | — | 1 | no | 30 |
| `full` | 300 | 300 (default) | 3 | sí (12m/3m) | 100 |

`--wf-epochs N` override solo el hyperopt de cada ventana walk-forward; las semillas siguen usando `--epochs` del perfil. Ver decisión pre-registrada en [`calibration_protocol.md`](calibration_protocol.md) antes del batch de las otras cuatro.

```bash
# CI / fontanería (sin hyperopt)
python -m pipeline.run_validation GridDCA --profile smoke --skip-hyperopt

# Validación completa (horas de CPU)
python -m pipeline.run_validation TrendRider --profile full
```

## Garantías de diseño

1. **Params-files (`<Estrategia>.json`)** — se limpian antes de cada run; se archivan en `user_data/validation_reports/<estrategia>/<run_id>/params/`; `param_load_check.py` verifica que el log coincida con el archivo esperado.
2. **IS/OOS 70/30** — fechas absolutas calculadas una vez y guardadas en `report.json` (`split.is_timerange`, `split.oos_timerange`).
3. **Hyperopt** — solo `--spaces buy sell`, `--random-state` por semilla, `QuantRobustLoss` (Sharpe + penalización drawdown + mínimo trades). El grid compite en la loss; no se fuerza su uso.
4. **Protecciones** — `--enable-protections` por defecto en IS, OOS y walk-forward (igual que dry-run).
5. **Walk-forward** — curva OOS cosida por tramos test; capital final de cada ventana = inicial de la siguiente.

## Caso de control (MeanRevBB)

MeanRevBB es el **termómetro de umbrales**, no una excepción en código. El veredicto es función pura de métricas para todas las estrategias.

**Procedimiento de calibración (OOS virgen una sola vez):**

Ver **protocolo pre-registrado** (leer *antes* del `report.json`): [`docs/calibration_protocol.md`](calibration_protocol.md)

1. `full` de MeanRevBB
2. Abrir reporte → seguir protocolo (ROBUSTA → endurecer *una* frontera; DUDOSA/SOBREAJUSTADA → congelar; DUDOSA marginal → resistir)
3. **Congelar** umbrales (commit) antes de lanzar las otras cuatro
4. Aceptar lo que salga — no retocar umbrales tras ver TrendRider u otras

**No ejecutar hasta congelar umbrales.** La calibración puede hacerse en cuanto MeanRevBB emita `report.json`; el bisect de `-j` no bloquea la calibración.

```powershell
# Tras decidir WF en calibration_protocol.md (opción A o B):
.\scripts\run_validation_batch.ps1 -AdoptPartialHyperopt
.\scripts\run_validation_batch.ps1 -WfEpochs 100 -AdoptPartialHyperopt   # opción B
# una sola: .\scripts\run_validation_batch.ps1 -Strategy TrendRider -WfEpochs 100 -AdoptPartialHyperopt
```

Si tras calibración MeanRevBB queda DUDOSA/SOBREAJUSTADA por números, el control funcionó.

## Imagen Docker (pin obligatorio)

`docker-compose.yml` fija `freqtradeorg/freqtrade@sha256:87aa5c6d65359b34e9d99a0bb260a38c0efe0315253811e6f48c2afe8f278a6a` (Python 3.14.6 al pin). El digest va en `report.json` → `docker_runtime.freqtrade_image_digest`. No usar `:stable` sin digest.

Probar candidato Py 3.12 para hyperopt paralelo (volumen aislado, no toca `hyperopt_results` del host):

```powershell
.\scripts\probe_py312_hyperopt.ps1
```

## Lockfile y reanudación

- `run_validation` crea `user_data/validation_reports/.run_lock.json` al arrancar (`pid`, `started_at`, `hostname`, `run_id`, `strategy`).
- Locks huérfanos: PID muerto o `started_at` > `VALIDATION_LOCK_MAX_HOURS` (default 168h) se limpian en `read_lock` / `python -m pipeline.run_lock check`.
- La limpieza **loguea siempre** el motivo (`pid` muerto vs antigüedad) vía `logging` en `pipeline.run_lock` — nunca actúa en silencio.
- Detección de PID: `psutil.pid_exists` si está instalado; en Windows, `OpenProcess` con tratamiento de `ACCESS_DENIED` como proceso vivo (evita falsos huérfanos entre procesos).
- Herramientas de diagnóstico abortan si hay run activo; `--force` para anular.
- `run_validation_batch.ps1` llama `python -m pipeline.run_lock check` antes del batch y entre estrategias.
- Tras cada semilla: `checkpoint.json` + copia de `hyperopt_results/` en `hyperopt_checkpoints/is_seed{N}/`.
- Reanudar: `python -m pipeline.run_validation MeanRevBB --profile full --resume-run-id <run_id>`.
- **Restauración manual del lock** — si un run vivo quedó desprotegido (p. ej. limpieza de huérfanos con falso negativo de PID), recrear `.run_lock.json` con el `pid`/`run_id`/`started_at` del proceso activo. Con el código de detección corregido y el PID vivo, `python -m pipeline.run_lock check` debe devolver `LOCKED`.

### Incidente: `hyperopt_tickerdata.pkl` y epoch 9/300 (2026-07-09)

Durante el primer intento de MeanRevBB `full`, `hyperopt_pickle_check.py` (sin `--force`) se ejecutó con un hyperopt activo. Ese probe puede **eliminar** `user_data/hyperopt_tickerdata.pkl` del volumen compartido; la corrida en curso falló en epoch **9/300** con `FileNotFoundError`.

**Matiz:** `hyperopt_tickerdata.pkl` es **contingente** — Freqtrade lo materializa en disco según versión/modo de hyperopt; otras corridas (p. ej. la actual a digest pinneado) pueden avanzar sin que el archivo exista en el volumen. La moraleja operativa no cambia: **no tocar `user_data/` ni herramientas de diagnóstico mientras `run_validation` esté activo** (salvo `--force` explícito). El fallo de aquella corrida fue borrar un artefacto que *esa* ejecución sí esperaba en disco, no la ausencia universal del `.pkl`.

### Incidente: timeout subprocess 7200 s en epoch 299/300 (2026-07-09)

El orquestador mató el hyperopt de seed 42 a las **7200 s (2 h)** con **299/300** epochs ya escritas en `.fthypt`. El proceso murió en **silencio** hasta que alguien miró el contador congelado.

| Qué pasó | Detalle |
|----------|---------|
| Síntoma | `.fthypt` congelado en 299/300; sin `checkpoint.json` |
| Causa | `run_hyperopt` usaba `timeout=7200` fijo |
| Fix | `hyperopt_timeout_seconds(epochs)` → **36000 s** para 300 epochs (~2 min/epoch de margen) |
| Override | `HYPEROPT_TIMEOUT_SECONDS=0` → sin límite |

**Walk-forward:** cada ventana llama al mismo `run_hyperopt` con **`epochs` del perfil** (300 en `full`). Con ventana IS 2021→2026 hay **18 ventanas** × 300 epochs — el timeout **por ventana** es el mismo (36 000 s); las ventanas cortas suelen ir más rápido por menos datos, pero el peor caso sigue acotado por la misma fórmula. Planificar **días** de CPU, no horas.

### Adopción de `.fthypt` parcial (reanudación barata)

Si un run muere tras ≥95 % de epochs, el archivo en `user_data/hyperopt_results/` suele ser válido. Para el **batch futuro** (no el run vivo):

```powershell
python -m pipeline.run_validation MeanRevBB --profile full --adopt-partial-hyperopt
# o: $env:HYPEROPT_ADOPT_PARTIAL=1
```

- Umbral: `HYPEROPT_ADOPT_MIN_RATIO` (default **0.95**).
- Valida con `freqtrade hyperopt-list` y exporta el mejor epoch a `<Estrategia>.json`.
- **No** sustituye `--resume-run-id` (semillas completadas en `checkpoint.json`).

### Vigilante de muerte silenciosa

```powershell
pwsh scripts/watch_validation.ps1 -Strategy MeanRevBB -IntervalSec 300 -StaleCycles 4
```

Cada intervalo: progreso `.fthypt`, `run_lock check`, PID vivo. Si el contador no sube **4 ciclos** con lock ON, o el PID murió → **beep** + `user_data/validation_reports/.run_failed.flag`.

## Hyperopt y reproducibilidad

- **Workers (`-j`)** — forma parte de la secuencia de puntos evaluados (junto a `--random-state`). Todas las semillas de un batch y el walk-forward deben usar el **mismo** `-j`. Si cambia `-j`, re-lanzar la estrategia completa, no semillas sueltas.
- **Valor por defecto** — `HYPEROPT_JOB_WORKERS=1` (variable de entorno). Queda en `report.json` como `hyperopt_job_workers` y en `docker_runtime`.
- **MeanRevBB (corrida actual)** — documentada como batch íntegro a `-j 1`; internamente consistente y válida aunque el batch de las otras cuatro use otro `-j` si el control vainilla lo justifica.
- **Diagnóstico pickle** — `user_data/tools/hyperopt_pickle_check.py` con `--inspect` (recursion limit + `__closure__`). Modo laboratorio vs `--vanilla` (SampleStrategy de `freqtrade/templates` + `user_data/fixtures/vanilla_hyperopt.json`).
- **Control vainilla (decisivo)** — `.\scripts\probe_vanilla_hyperopt_parallel.ps1` (respeta lock; no monta `hyperopt_results` del host):
  - **SampleStrategy + `vanilla_hyperopt.json` + `-j 2`** → hyperopt **completa** (2 workers efectivos).
  - **MeanRevBB + `base.json`/`backtest.json` + `-j 2`** → `PicklingError` real en joblib.
  - **Conclusión:** el paralelismo funciona en este Docker; el fallo es **específico del stack config/user_data del laboratorio**, no Python 3.14 ni bug genérico de Freqtrade. No abrir issue upstream con el borrador antiguo.
- **Nota sobre `hyperopt_pickle_check.py`** — **no es oráculo.** `cloudpickle.dumps` del closure puede fallar (`_thread.lock`) incluso donde hyperopt `-j 2` completa. El probe es orientativo (`--inspect`, recursion, `__closure__`); **el test decisivo es ejecutar hyperopt con `-j 2`** (`probe_vanilla_hyperopt_parallel.ps1`). No usar el probe para decidir si un batch paralelo funcionará.
- **Bisect post-MeanRevBB** — matriz 2×2 config vs `user_data` en `docs/HYPEROPT_PARALLEL_BISECT.md`; script `scripts/probe_hyperopt_bisect.ps1` (celdas B y C). No bisectar el config por secciones hasta localizar el eje.
- **Grep config (hipótesis)** — `backtest.json` limpio; `base.json` tiene telegram/api_server enabled. No demostrado que arranquen en hyperopt — celda B decide. Higiene post-MeanRevBB; `config_merged_sha256` en `report.json`.
- **Prueba Py 3.12** — `freqtrade:2025.3` también falla con MeanRevBB `-j 2`; coherente con eje config/código del lab, no versión de Python.

## Entorno: pipeline local vs Docker

El orquestador `pipeline/` en Windows **no** importa `talib`, `freqtrade` ni estrategias. Solo lanza subprocesos Docker y parsea JSON/zip. `regime_stats.py` calcula régimen vía `docker compose run --entrypoint python` (versión anterior importaba `_base` en host → `ModuleNotFoundError: talib`).


## Reportes

`user_data/validation_reports/<estrategia>/<run_id>/report.json` — incluye `git_hash`, `config_files`, `config_merged_sha256`, split, `oos_regime_distribution`, `hyperopt_job_workers`, `docker_runtime`, semillas, WFE y veredicto.

- `conclusive: true` — solo perfil `full`
- `conclusive: false` + `conclusive_note` — perfil `smoke` (no citar veredicto como validación)

## Tests de integración (cadencia)

Los guards Docker (`regime_variety_check`, `signal_truncation_check`, etc.) deben invocarse **igual que** `scripts/backtest_all.ps1`: solo `--config`, sin `--datadir` en las herramientas programáticas (el datadir de fixtures lo fija `fixture_config`).

Si el CI no ejecuta `pytest -m integration` en cada push (coste ~5 min), programar al menos un job **nocturno** o **pre-batch** (`scripts/run_integration_tests.ps1`). Una suite de integración que solo corre “cuando toca” deriva en silencio — los unitarios no detectan contratos CLI rotos entre tests y scripts.
