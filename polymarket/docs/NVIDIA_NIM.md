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

- **Modo rápido (default):** `NVIDIA_NIM_MODE=fast` — si las reglas de seguridad pasan, **cotiza al instante** sin llamar API (~0 ms). NIM solo en modo `full`.
- **Hybrid + profit assist:** `NVIDIA_NIM_PROFIT_ASSIST=1` — sube el umbral `rule_strong_edge` (`NVIDIA_NIM_STRONG_EDGE_MULT`, p.ej. 1.7) para que más entradas pasen por NIM, y pregunta a NIM cada `NVIDIA_NIM_EXIT_EVERY_S` s si **hold** o **flatten** con inventario abierto (maximizar PnL de sesión). Sigue **sin** cambiar precios/fair.
- **Modelo (modo full):** `meta/llama-3.2-1b-instruct` por defecto (`NVIDIA_NIM_MODEL` opcional).

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
