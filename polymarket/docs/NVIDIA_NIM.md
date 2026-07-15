# NVIDIA NIM — motor de decisiones (Polymarket)

## Qué hace

NVIDIA Build (`integrate.api.nvidia.com`) alimenta el **motor de decisiones** del paper maker:

- **No predice** resultados de mercados — eval LLM naive (#17) **abortado** 2026-07-15; ver `llm-forecast-lab/docs/CLOSURE.md`.
- **Sí decide** si publicar cotización, refrescar o pausar (`quote` / `cancel_replace` / `hold`).

## Configuración

En `trading/.env`:

```env
NVIDIA_API_KEY=nvapi-...
# opcionales:
NVIDIA_NIM_MODEL=nvidia/nemotron-mini-4b-instruct
NVIDIA_NIM_CONFIDENCE_MIN=0.55
```

La key debe tener scope **Public API endpoints** en [build.nvidia.com](https://build.nvidia.com).

## Arquitectura

```
paper_maker.py
    └── decision_engine.py
            ├── rule_guard()     ← seguridad determinista (sin API)
            └── nvidia_client.py ← chat/completions + cache local
```

- **Cache de decisiones:** `polymarket/data_local/nim_decision_cache/` (mismo snapshot → misma respuesta).
- **Cache de catálogo:** `polymarket/data_local/nvidia_models_cache.json`.

## Errores comunes

| Error | Causa | Fix |
|-------|-------|-----|
| 403 Forbidden | Key sin scope Public API | Nueva key en build.nvidia.com |
| 429 Too Many Requests | Rate limit | Backoff automático; cache reduce llamadas |
| `NVIDIA_API_KEY missing` | `.env` no cargado | Key en `trading/.env`; paper carga automático |

## Comandos

```powershell
cd C:\Users\carom\Desktop\trading

# Smoke test API
python -m polymarket.research.local_lab.test_nvidia_nim

# Paper 30 min (requiere NIM)
python -m polymarket.research.local_lab.run_local_lab --paper --strategy maker_16 --minutes 30
```

## Salida de sesión

- `report.json` — fills, adverse_rate, `nim_decisions_used`, `nim_rule_holds`, `nim_cache_hits`
- `decisions.jsonl` — traza de cada decisión NIM/regla

**No proyectar PnL.** El lab solo puede matar ideas; ver `LOCAL_LAB.md`.
