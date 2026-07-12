# Incidentes de validación — registro pre-mortem

## #8 — Lock ausente con orquestador vivo (2026-07-10)

### Síntoma

`user_data/validation_reports/.run_lock.json` **no existía** mientras `python` pid **38004** seguía ejecutando hyperopt de MeanRevBB (`--resume-run-id 20260709_162954`). `python -m pipeline.run_lock check` devolvía `OK: sin lock`.

### Hipótesis descartada: resume sin adquirir lock

Lectura de `pipeline/run_validation.py` (sin modificar con run vivo):

- Tanto run nuevo como `--resume-run-id` entran en `with _validation_lock(...)` (línea ~324).
- `_validation_lock` llama `acquire_lock` al entrar y `release_lock` al salir.

**Conclusión:** el resume **sí** adquiere lock en código actual. No es el mismo bug que el incidente de PID huérfano (#3).

### Hipótesis abiertas

1. `read_lock()` / `clear_stale_lock()` invocado por otra herramienta con falso negativo de PID (transitorio en Windows).
2. Borrado manual o herramienta externa del archivo (`.gitignore` reciente del lock).
3. `release_lock()` desde proceso hijo con mismo PID (improbable).
4. Race no reproducida aún.

### Mitigación inmediata

Restauración manual de `.run_lock.json` con pid/run_id/started_at del orquestador vivo (procedimiento documentado en `docs/VALIDATION.md`).

### Fix post-lock (pipeline/)

1. **Audit-log append-only** — toda escritura/borrado de `.run_lock.json` pasa por una función única que registra en `user_data/validation_reports/.run_lock_audit.log`: timestamp UTC, PID del actor, operación (`acquire` / `release` / `stale_clear` / `heartbeat` / `manual_restore`), motivo. Si el lock desaparece sin línea en el audit-log, el sospechoso es externo (AV, sync, limpieza OS).
2. **Heartbeat** — el orquestador renueva el lock cada N minutos (mismo pid/run_id, `started_at` original); detecta lock presente-pero-congelado y permite criterio de huérfano por antigüedad del heartbeat, no solo PID-vivo.
3. Tras `acquire_lock`, verificar que el archivo existe y loguear ruta + pid (también al audit-log).
4. Test de integración: `--resume-run-id` deja lock presente tras arranque.

### Comprobación entorno (2026-07-10)

- Repo en `C:\Users\carom\Desktop\trading` — **no** bajo `C:\Users\carom\OneDrive\`.
- Desktop no resuelve a ruta OneDrive en este host. Sync de nube descartado como causa obvia; no excluye AV ni otras herramientas.

---

## Near-miss — screen backtest pisó `.last_result.json` (2026-07-10)

### Síntoma

Backtest de humo de RelativeMomentum (Docker) actualizó `user_data/hyperopt_results/.last_result.json` / `user_data/backtest_results/` compartidos con el pipeline. Restauración manual evitó archivar zip equivocado al terminar seed 123.

### Fix post-lock (`screen_strategy.py`)

- Backtests del screen con `--export-directory` / directorio dedicado bajo `user_data/validation_reports/screen/`.
- Snapshot + restore automático de `.last_result.json` alrededor de cada backtest si no hay export aislado.
- **Regla:** paralelismo seguro = aislamiento de estado, no cuidado manual.

---

## Apagón servidor + resume WF granular (2026-07-12)

### Síntoma

Servidor apagado por el usuario ~03:30 tras completar WF ventanas 0–5 (`wf0`…`wf5_train.json` en disco). Al reiniciar (~10:33), PM2 relanzó `--resume-run-id 20260709_162954` pero el pipeline **rehizo WF desde ventana 0** (sin checkpoint por ventana). Pérdida: ~6 ventanas de hyperopt + ventana 6 parcial.

### Causa apagón

Diagnóstico sin privilegios root en journal/dmesg completo. `uptime` tras reboot: ~10:33 (uptime 1h54 a las 12:27). **Hipótesis principal: apagado manual / corte eléctrico**, no OOM (sin evidencia en logs accesibles; disco 87%, RAM holgada antes del stop).

### Mitigación aplicada

- **`pipeline/wf_resume.py`**: skip de ventanas WF si `wfN.json` (segment) coincide timerange con el plan, o recuperación desde `wfN_train.json` por backtest IS+OOS (sin re-hyperopt).
- **`checkpoint.json`**: campo `wf_windows_completed[]` actualizado tras cada ventana.
- Rechazo explícito si `hyperopt_timerange` en meta ≠ plan (caso PC1 pre-fix warmup `20210101-*`).
- Parada deliberada 12:27 para desplegar fix; resume con adopción ventanas 0–5 de anoche.

### Lección

Tercer incidente de muerte en 72h. Sin resume granular, probabilidad de completar 32h+ seguidas era baja. **No apagar el servidor** hasta `report.json`.

---

| Item | Archivo | Prioridad |
|------|---------|-----------|
| Lock **audit-log** + heartbeat | `pipeline/run_lock.py`, tests | Alta (antes del batch) |
| Test resume deja lock | `tests/test_validation_pipeline.py` | Alta |
| Screen export aislado | `user_data/tools/screen_strategy.py` | Alta |
| Matrices CI RelativeMomentum | `backtest_all.ps1`, `test_smoke_backtest.py` | Media |
| Guards + screen datos reales | operación | Tras lock libre |
