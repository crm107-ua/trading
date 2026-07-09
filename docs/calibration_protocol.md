# Protocolo de calibración de umbrales (pre-registro)

**Congelar este protocolo antes de leer el `report.json` de MeanRevBB.**  
La calibración decidida *después* de ver los números es racionalización, no calibración.

Orden de lectura cuando aterrice el reporte:

1. Este protocolo (qué hacer según veredicto emitido).
2. **Métricas primero** — tabla abajo, sin mirar aún `verdict` ni `reasons`.
3. **Veredicto y `reasons` al final** — para que la lectura de números no esté teñida por saber qué dictaminó el motor.
4. Decisión: endurecer / congelar / resistir — **sin mirar otras estrategias**.

## Qué leer del reporte (checklist)

Leer en este orden; **dejar `verdict` y `reasons` para el paso final.**

| Orden | Campo | Dónde |
|-------|--------|--------|
| 1 | Sharpe IS/OOS por semilla | `steps.seeds[].is_metrics.sharpe`, `oos_metrics.sharpe` |
| 2 | Degradación IS→OOS | comparar por semilla; motor usa **semilla 42** como primaria |
| 3 | PnL OOS | `steps.seeds[].oos_metrics.profit_total` |
| 4 | WFE | `steps.walk_forward_efficiency` |
| 5 | Dispersión de parámetros | `max_param_divergence`, `steps.seeds[].param_divergence_vs_seed0` |
| 6 | Baseline OOS defaults | `steps.baseline_oos_defaults` |
| 7 | Config del run | `config_merged_sha256`, `hyperopt_job_workers`, `docker_runtime` |
| **último** | Veredicto emitido | `verdict`, `reasons`, `verdict_details` |

**Nota de motor:** `verdict_engine.py` **sí consume** `max_param_divergence` (> `DEFAULT_MAX_PARAM_DIVERGENCE` → motivo en `reasons`, veredicto DUDOSA salvo hard-fail). No es decorativo en el JSON. Las métricas Sharpe/PnL del veredicto salen de la **semilla 42** (primera); las otras semillas aparecen en el reporte para lectura humana y divergencia agregada.

## Semilla primaria (42) — convención congelada para este ciclo

Usar la semilla **42 fijada de antemano** es una convención legítima: arbitraria, pero **pre-registrada** — eso es lo que importa.

| Propuesta | Veredicto del protocolo |
|-----------|-------------------------|
| Mantener semilla 42 como primaria | ✅ **Este ciclo** (MeanRevBB en curso + calibración) |
| Migrar a “la mejor de las tres” | ❌ **Sesgo de selección** — puerta cerrada |
| Alternativa honesta si algún día se revisa | **Mediana** de las tres semillas, **nunca el máximo** |

La mediana, con 3 semillas, evita que un OOS bueno por suerte en la primaria infle el veredicto.

**No cambiar ahora** — la corrida en curso y el protocolo de calibración están definidos así. Candidato a revisión **solo después** de calibrar y congelar umbrales, y **solo si se decide antes de ver ningún resultado del batch** de las otras cuatro. Si no se decide entonces, el batch corre con semilla 42 primaria como MeanRevBB.

## Reglas de decisión (pre-comprometidas)

### 1. Endurecer umbrales — solo si sale **ROBUSTA**

MeanRevBB pasó todos los filtros. La tentación es endurecer “todo”; **no**.

| Paso | Acción |
|------|--------|
| 1 | Leer métricas (checklist) — **sin** `verdict`/`reasons` aún. |
| 2 | Leer `verdict` y `reasons`. |
| 3 | Identificar **qué métrica** la dejó pasar con margen (solo si ROBUSTA): ¿Sharpe OOS bajo pero > umbral? ¿degradación IS→OOS justo dentro del 50%? ¿WFE alto con pocas ventanas WF? ¿`max_param_divergence` bajo pero no cero? |
| 3 | Endurecer **solo esa frontera** en `verdict.py` / `verdict_engine.py` (una constante o regla, no un barrido). |
| 4 | Re-evaluar MeanRevBB con umbrales nuevos (mismo reporte guardado + re-run veredicto offline o re-validación si hace falta). |
| 5 | Si sigue ROBUSTA tras endurecer → repetir pasos 1–4 una vez más como máximo; luego congelar. |
| 6 | **Commit** de umbrales congelados antes del batch de las otras cuatro. |

### 2. No tocar nada — si sale **DUDOSA** o **SOBREAJUSTADA**

Los umbrales **ya discriminan** el control. El control cumplió su función.

| Acción | |
|--------|--|
| Congelar `verdict.py` / `verdict_engine.py` **tal cual** | ✅ |
| “Aprovechar para afinar” porque MeanRevBB “debería” ser mala | ❌ |
| Relanzar MeanRevBB con otros umbrales hasta obtener el veredicto intuitivo | ❌ |

### 3. Caso trampa — **DUDOSA por poco**

El motor dice DUDOSA con un motivo marginal (p. ej. divergencia 0.26 vs umbral 0.25, o trades IS 98 vs 100).

| Tentación | Respuesta del protocolo |
|-----------|-------------------------|
| Mover el umbral un pelo para que salga SOBREAJUSTADA “como debería” | **Resistir** |
| Reclasificar manualmente en la cabeza | **No** — el veredicto emitido es el dato |

**DUDOSA es válida** para el termómetro. El motor no replica intuición; discrimina. Si el control queda DUDOSA, congelar umbrales y registrar en commit message que el control no pasó limpio — eso también es un resultado informativo.

## Después de congelar

1. Batch de las otras cuatro (`scripts/run_validation_batch.ps1`) sin retocar umbrales.
2. Aceptar lo que salga.
3. Bisect `-j` y higiene de config en paralelo o después; no mezclar con calibración.

## Referencia de umbrales actuales (`verdict.py`)

| Constante | Valor | Rol |
|-----------|-------|-----|
| `DEFAULT_OOS_SHARPE_RATIO_MIN` | 0.5 | OOS Sharpe ≥ 50% del IS (semilla 42) |
| `DEFAULT_WALK_FORWARD_EFFICIENCY_MIN` | 0.5 | WFE mínimo |
| `DEFAULT_MAX_PARAM_DIVERGENCE` | 0.25 | Inestabilidad entre semillas |
| `DEFAULT_MIN_TRADES_HYPEROPT` | 100 | Trades mínimos IS |

Hard-fail → SOBREAJUSTADA: PnL OOS negativo, degradación Sharpe, WFE bajo.  
Otros motivos (divergencia, trades IS) → DUDOSA.
