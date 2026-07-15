# Cierre #17 — eval LLM naive (2026-07-15)

**Veredicto operativo:** `ABORTADO` — no hay `report.json` vinculante de skill.

| | Detalle |
|---|---------|
| **Hipótesis** | Forecaster NVIDIA NIM `meta/llama-3.3-70b-instruct` (pipeline `naive`, sin retrieval) vs precio de mercado como predictor probabilístico |
| **Progreso al cierre** | Forecast **375 / 1.471** (~25,5 %), **375 OK**, **0 fallos**; ingest + gate + CLOB completos |
| **Motivo del cierre** | Decisión estratégica: sin vía creíble a PnL; el eval mide calibración, no edge tradeable; expectativa pre-reg ya era `BELOW_MARKET` / `MATCHES_MARKET` |
| **Qué NO implica** | No es veredicto empírico `BELOW_MARKET` — no interpretar skill de reports parciales |
| **Artefactos conservados** | `data/lab.sqlite`, `data/responses/`, `output/forecast_state.json` |
| **Reapertura** | Prohibida sin pre-reg nuevo (#18+): decomposed, ensemble, retrieval, etc. |

## Dos líneas (ritual día D — cierre anticipado)

1. **Línea naive NIM cerrada por decisión, no por datos:** no se completó el eval v1; no hay claim estadístico de skill vs mercado.
2. **Siguiente bifurcación Polymarket:** #16 maker (pre-reg existente) u otra hipótesis pre-registrada — no optimizar prompt naive ni reanudar forecast 70B.

## Comandos desactivados

No ejecutar salvo auditoría forense:

```powershell
# NO reanudar eval v1
# .\scripts\resume_forecast.ps1
# .\scripts\run_after_forecast.ps1
```

Checkpoint final: `output/forecast_state.json` (2026-07-15 ~16:40 UTC).
