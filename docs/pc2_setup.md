# Setup PC2 — freqtrade-quant-lab (research / desarrollo)

**Fecha:** 2026-07-10  
**Equipo:** `carlos` (PC2)  
**Rama:** `pc2/setup` (cambios de pipeline **no** mergeados a `main` hasta que PC1 libere el lock de MeanRevBB)

---

## 1. Reglas de coordinación (confirmadas)

| Acción | PC2 |
|--------|-----|
| `python -m pipeline.run_validation` | **PROHIBIDO** |
| Hyperopt (cualquier tipo) | **PROHIBIDO** |
| Docker / `docker compose` | **PROHIBIDO** por defecto |
| Escribir en `user_data/validation_reports/` pensando en fusionar con PC1 | **PROHIBIDO** |
| Research pandas en `research/` | ✅ |
| Tests unitarios (`pytest -m "not integration"`) | ✅ |
| Código + docs en rama git | ✅ |
| Sincronización entre PCs | **Solo git** (pull al abrir, commit+push al cerrar) |
| Copiar `user_data/data/`, locks, `hyperopt_results/`, `validation_reports/` a mano | **PROHIBIDO** |

El lock `.run_lock.json` es **por máquina**. PC1 puede tener MeanRevBB LOCKED mientras PC2 trabaja en research; no hay interferencia si se respetan las reglas anteriores.

---

## 2. Entorno instalado

| Componente | Versión / detalle |
|------------|-------------------|
| SO | Windows 10 (build 26200) |
| Hostname | `carlos` |
| Python | 3.14.3 |
| Gestor deps | `pip install -e ".[dev]"` (`pyproject.toml`, `requires-python >= 3.11`) |
| Repo remoto | `git@github.com:crm107-ua/trading.git` |
| `.env` | Creado desde `.env.example` (sin claves reales) |
| Docker Desktop | No usado en esta sesión |

### Verificación de tests

```text
python -m pytest tests/ -m "not integration" -q
→ 135 passed, 1 skipped, 28 deselected (21.5s)
```

Tests de integración (Docker) excluidos: `pytest -m integration` — no ejecutar en PC2.

---

## 3. `.gitignore` actualizado

Se amplió para evitar commits accidentales desde PC2:

- `user_data/data/`
- `user_data/hyperopt_results/`
- `user_data/strategies/*.json`
- `user_data/validation_reports/**` (excepto `.gitkeep`)
- `research/data_local/`
- `.env`

**Nota para PC1:** archivos ya trackeados en git (datos feather, reportes antiguos, `.fthypt`) siguen en el historial. Tras la validación MeanRevBB, conviene un commit de limpieza en PC1 con `git rm --cached` sobre esos artefactos. El `.gitignore` nuevo evita que vuelvan a entrar.

---

## 4. Datos locales PC2

Descarga **solo 1d del universo E2** (16 pares), sin Docker:

```bash
python research/download_e2_local.py
```

| Campo | Valor |
|-------|--------|
| Destino | `research/data_local/binance/` |
| Pares | 16/16 OK (AAVE, ADA, BNB, BTC, DEXE, DOGE, ETH, LTC, NEAR, SKL, SOL, TRX, UNI, XLM, XRP, ZEC) |
| Fuente | Binance API `v3/klines` (intervalo 1d, desde 2021-01-01) |
| Manifiesto local | `research/data_local/e2_download_manifest.json` (gitignored) |

`research/pc2_xsec_robustness.py` usa `research/data_local/binance` si existe; si no, cae a `user_data/data/binance`.

### Resultados de robustez XSecMomentum (pandas, pre-validación)

Informe: `research/output/pc2_xsec_robustness.json`

| Hallazgo | Valor |
|----------|--------|
| Muestra completa bear_flat | wealth 6.35× vs 4.33× sin filtro (+47% relativo) |
| Régimen BTC@1d | RANGE 50%, BULL 27%, BEAR 23% |
| Años fuertes | 2023–2024 y 2026 YTD (bear_flat) |
| Año débil | 2022 (bear market; ambas variantes negativas) |
| LOO sin DEXE | wealth 6.03× (vs 6.35× con DEXE — impacto moderado) |
| DEXE | log_pnl +0.15, vol medio ~364k USDT/día (bajo vs XRP ~405M) |
| Top contribución PnL | ZEC, SOL, XRP (ZEC alto PnL con volumen medio bajo — vigilar) |

Estos números son **triaje research**, no sustituyen el screen/validación Freqtrade en PC1.

---

## 5. Deudas pre-batch implementadas (rama `pc2/setup`)

### 5.1 Audit-log + heartbeat (`pipeline/run_lock.py`)

- Log append-only: `user_data/validation_reports/.run_lock_audit.log`
- Operaciones: `acquire`, `release`, `stale_clear`, `heartbeat`
- Heartbeat renovado desde `run_validation` en cada fase larga
- Huérfano por PID muerto, antigüedad total (`VALIDATION_LOCK_MAX_HOURS`, default 168h) o heartbeat viejo (`VALIDATION_LOCK_HEARTBEAT_MAX_HOURS`, default 6h)
- Tests: `tests/test_run_lock_audit.py`

### 5.2 Git hash por paso (`pipeline/git_provenance.py`)

`report.json` incluye `pipeline_provenance.steps`:

- `validation_start`, `seeds`, `walk_forward`, `verdict`

Cada entrada: `git_hash` + `recorded_at` UTC.

### 5.3 Test resume deja lock

`test_resume_run_leaves_lock_during_startup` — `--resume-run-id` adquiere lock al arrancar.

### 5.4 Fixture XSecMomentum

`tests/test_xsec_momentum_fixture.py` marcado `@pytest.mark.integration` (requiere Docker).

---

## 6. Workflow recomendado en PC2

```bash
git pull origin main          # o merge de main en pc2/setup
pip install -e ".[dev]"
python -m pytest tests/ -m "not integration" -q
# research...
git add ...
git commit -m "..."
git push origin pc2/setup
```

**No hacer** `git pull` de `pc2/setup` en PC1 mientras MeanRevBB está en walk-forward, salvo revisión explícita del diff de pipeline.

---

## 7. Estado PC1 al cierre de esta sesión

- MeanRevBB validación full en curso (PC1); lock activo
- XSecMomentum (#10): screen PASA; validación full **detrás** de calibración MeanRevBB
- Cambios de esta rama listos para review/merge post-lock
