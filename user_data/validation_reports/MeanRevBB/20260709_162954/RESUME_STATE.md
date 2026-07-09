# Estado de retoma — MeanRevBB full

**Capturado:** 2026-07-09 ~22:31 (UTC+2) — antes de apagar el PC.

## Run

| Campo | Valor |
|-------|-------|
| `run_id` | `20260709_162954` |
| Estrategia | MeanRevBB |
| Perfil | `full` (300 epochs, 3 semillas, walk-forward) |
| Inicio run | `2026-07-09T16:29:54+00:00` (18:29 local) |
| PID orquestador (muerto tras apagar) | `38520` |
| `report.json` | **No existe aún** |

## Progreso guardado en checkpoint

| Fase | Estado |
|------|--------|
| Baseline OOS | Hecho (en `checkpoint.json`) |
| Semilla 42 | **Completada** (~3h52 punta a punta) |
| Semilla 123 | **En curso** — hyperopt interrumpido (~epoch 5/300) |
| Semilla 456 | Pendiente |
| Walk-forward | Pendiente (sin checkpoint por ventana) |

Archivo hyperopt activo al apagar: `strategy_MeanRevBB_2026-07-09_20-22-37.fthypt` (~5/300).

**Nota:** el checkpoint solo persiste semillas **terminadas**. La 123 se rehace entera al reanudar (`--adopt-partial-hyperopt` no estaba activo).

## WF — epochs (respuesta al grep)

En `run_validation.py` línea ~490, cada ventana WF llama `_hyperopt_and_archive(..., epochs=epochs_n, ...)`.

Con perfil `full`, `epochs_n = 300` — **igual que las semillas**. No hay perfil reducido por ventana.

Ventanas WF: ~16 (12m train / 3m test / paso 3m sobre `20210101-`). El WF **no** tiene resume incremental; si muere en WF, rehace todas las ventanas desde cero.

## Estimación revisada (post-apagado)

| Bloque | Horas aprox. |
|--------|----------------|
| Semillas 123 + 456 (desde cero) | ~8 h |
| WF 16 × 300 epochs (train 12m, más rápido que IS completo) | ~20–50 h |
| **Total desde retoma** | **~1,5–2,5 días** máquina encendida |

Ventana realista del `report.json` si retomas mañana (viernes): **domingo 12 – lunes 13 jul**. No es un run de “sábado por la mañana”.

## Mañana — retomar

```powershell
cd c:\Users\carom\Desktop\trading

# 1. Docker / freqtrade arriba (si aplica)
docker compose up -d

# 2. El lock huérfano se limpia solo al adquirir lock (PID muerto)
python -m pipeline.run_lock check

# 3. Reanudar — omite semilla 42, reinicia 123 (adopt-partial evita rehacer si ≥95%)
python -m pipeline.run_validation MeanRevBB --profile full --resume-run-id 20260709_162954 --adopt-partial-hyperopt
```

## Antes del batch (mientras corre MeanRevBB — decidir por escrito)

- [ ] Calibración MeanRevBB + umbrales congelados en git.
- [ ] **WF del batch:** opción A (300/ventana, ~2 sem) vs B (`--wf-epochs 100`, ~5–6 días) — ver `docs/calibration_protocol.md`.
- [ ] Batch con `--adopt-partial-hyperopt` (ya en `run_validation_batch.ps1 -AdoptPartialHyperopt`).
- MeanRevBB control: WF sigue a 300; WFE del batch no comparable en precisión si usa 100.

Opcional vigilante (otra terminal):

```powershell
pwsh scripts/watch_validation.ps1 -Strategy MeanRevBB -Seeds 3 -Epochs 300
```

## Señales de vida (sin abrir métricas)

| Fase | Señal sana | Atasco |
|------|------------|--------|
| Semillas | `checkpoint.json` gana 123, luego 456 | Lock LOCKED + mismo `.fthypt` sin líneas nuevas **15–20 min** |
| WF (tras 456) | Etiqueta `WF` en vigilante; **nuevo `.fthypt` cada ~1–3 h** | Lock LOCKED + **5–6 h** sin `.fthypt` nuevo |
| Fin | Aparece `report.json` de golpe | Lock OFF sin `report.json` → revisar terminal / traceback |

## Disciplina

- No evaluar métricas parciales de seeds 123/456 ni ventanas WF.
- Próxima conversación sustantiva: `report.json` íntegro (o traceback + checkpoint si falla).
- Caso borde Sharpes negativos: ya cerrado en `verdict_engine.py` + `calibration_protocol.md`.

## Cambios en código listos (no afectan run hasta retoma)

- `verdict_engine.py`: degradación Sharpe omitida si OOS ya falla por rentabilidad.
- `scripts/watch_validation.ps1`: contexto `semilla N/3 arch N/3` y fase `WF`.
