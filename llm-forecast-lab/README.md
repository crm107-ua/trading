# LLM Forecast Lab

Framework de evaluación reproducible para medir si pipelines de forecasting con LLM igualan o superan el baseline de **precio de mercado** en preguntas binarias.

**No es un sistema de trading**: no hay wallet, no hay órdenes, no hay capital en riesgo y no existe métrica de PnL en el codebase.

## Principios

- **Métrica de éxito**: calibración (Brier, log loss, ECE), no dinero.
- **Protocolo congelado**: `config/eval_frozen.json` (hash verificado en runtime).
- **Determinismo**: `temperature=0`, seeds fijos y cache en disco de respuestas LLM.
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
node dist/cli.js report --mode fixtures
```

