# LEAKAGE (temporal integrity)

Un LLM con cutoff de entrenamiento \(C\) puede “predecir” preguntas resueltas antes de \(C\) usando memoria del dataset de entrenamiento.
Esto invalida cualquier evaluación si no se controla.

## Política v1

- `config/models.json` declara `trainingCutoff` por modelo.
- Una pregunta es **elegible** solo si:

\[
resolution\_date > cutoff + safety\_margin
\]

- `safety_margin_days` es parte del protocolo congelado (`eval_frozen.json`).

## Canary leakage test

Se selecciona un pequeño conjunto de **canarios**: preguntas resueltas **antes** del cutoff.
Si el modelo obtiene un Brier sospechosamente cercano a 0 en canarios, el reporte marca:

- `EVAL_INVALID: leakage_suspected`

## Límites

En v1 no hay retrieval (`retrieval: none`). La instrucción “congelar conocimiento” en prompts mitiga, pero no garantiza.

