# LLM Forecast Lab

Framework de evaluación reproducible para medir si pipelines de forecasting con LLM igualan o superan el baseline de **precio de mercado** en preguntas binarias.

**No es un sistema de trading**: no hay wallet, no hay órdenes, no hay capital en riesgo y no existe métrica de PnL en el codebase.

## Principios

- **Métrica de éxito**: calibración (Brier, log loss, ECE), no dinero.
- **Protocolo congelado**: `config/eval_frozen.json` (hash verificado en runtime).
- **Determinismo**: `temperature=0`, seeds fijos y cache en disco de respuestas LLM.
- **v1**: pipeline `naive` vía provider NVIDIA (`NVIDIA_API_KEY` en `.env` del repo raíz).
- **CI sin red**: tests corren desde cache/fixtures (sin llamadas externas).

## Comandos

```bash
cd llm-forecast-lab
npm i
npm test
```

Ejemplo CLI (fixture/integración usa solo cache):

```bash
node dist/cli.js ingest --source polymarket --mode fixtures
node dist/cli.js forecast --pipeline naive --mode fixtures --no-network
node dist/cli.js score --mode fixtures
node dist/cli.js report --mode fixtures --pipeline naive
```

Live (requiere `NVIDIA_API_KEY` en `../.env`):

```bash
node dist/cli.js ingest-canaries
node dist/cli.js ingest-cascade
node dist/cli.js forecast --pipeline naive --mode live --model meta/llama-3.3-70b-instruct --provider nvidia
node dist/cli.js score --mode live
node dist/cli.js report --mode live --pipeline naive
```

**Forecast live:** ~1.500 llamadas × ~20 s/llamada (70B) ≈ **8–12 h** en serie, más rate limits del tier gratuito. Ejecutar desatendido (noche entera); reanudable vía cache en disco + `purge` live al reiniciar.
```

