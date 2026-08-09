# Context Engineering — pipeline NIM (Polymarket)

**Fuente:** *Context Engineering: The Discipline Nobody Named Until It Was Already Load-Bearing* (wast3 / @0xWast3).

Prompt engineering decide *cómo* hablarle al modelo. Context engineering decide *qué* se le permite saber — y qué se queda fuera — en cada request.

## Por qué está aquí

El paper maker llama a NVIDIA NIM en bandas ambiguas (`hybrid` / `full`). El snapshot crudo mezcla book, edge, riesgo, sesión y trazas. Sin curación, tokens irrelevantes diluyen atención y suben coste.

Este pipeline alimenta el mensaje de usuario de NIM con el mínimo footprint útil.

## Etapas

```
ingest → rank → route → compress → assembled context
```

| Etapa | Módulo | Rol |
|-------|--------|-----|
| **Ingest** | `ingest_market_snapshot` | Normaliza heterogeneidad (book / edge / risk / session / decisions) en `IngestedChunk` con provenance |
| **Rank** | `rank_chunks` | Blend semántico (0.55) + recencia (0.25) + autoridad (0.20) |
| **Route** | `route_request` | `MINIMAL` / `STANDARD` / `DEEP` / `TOOL_ONLY` según score y complejidad |
| **Compress** | `compress_chunk` | Estructural / extractivo (abstractivo opcional) sin truncar a ciegas |

Código: `polymarket/src/ai/context_engineering.py`  
Integración: `decision_engine.assemble_quote_context` → `_build_nim_messages`

## Flags

```env
NVIDIA_NIM_CONTEXT_ENGINEERING=1   # default on
CONTEXT_ENGINEERING_ABSTRACTIVE=0  # off: sin SDK Anthropic en hot path
```

Desactivar vuelve al JSON legacy del snapshot completo.

## Paper ultra (feeds reales)

Config de referencia: `polymarket/config/maker_demo_grind_nim_v2.json` (`demo_label: grind_nim_v2_ultra`).

```powershell
$env:NVIDIA_NIM_MODE = "hybrid"
$env:NVIDIA_NIM_PROFIT_ASSIST = "1"
$env:NVIDIA_NIM_GRIND = "1"
$env:NVIDIA_NIM_CONTEXT_ENGINEERING = "1"

python -m polymarket.research.local_lab.run_local_lab `
  --paper --strategy maker_16 --minutes 15 `
  --config polymarket/config/maker_demo_grind_nim_v2.json
```

Cada línea de `decisions.jsonl` incluye `context_route`, `context_sources`, `context_tokens`.

## Tests

```powershell
python -m pytest polymarket/tests/test_context_engineering.py polymarket/tests/test_decision_engine.py -q
```
