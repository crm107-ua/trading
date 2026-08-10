# Por dónde seguir la investigación (hacia inversión real)

## Diagnóstico
| Bloqueo | Estado |
|---------|--------|
| Evidencia DNA | n≈11, Wilson≈0.74 → falta n≥50 / Wilson≥0.80 |
| CLOB history | vacío incluso post-julio en probes → **solo forward** |
| Edge live | HK gap~4¢ UD stuck; BJ 2/3 espera basket |
| Capital | ~$3.45 no aguanta 1 miss (sim $25 sí) |

## Camino
1. Forward snapshots D+0..D+3 + recheck denso (30–45s cerca).
2. `resolve_forward_cases` añade **y actualiza** cases al cerrar.
3. `evidence_sprint` cada ~3 min → `MONEY_READY_STATUS.md`.
4. Meter dinero **solo** si `READY_TO_REARM` + `can_recommend_deposit`.

## Comandos
```bash
python -m polymarket.research.local_lab.resolve_forward_cases
python -m polymarket.research.local_lab.assurance_research --write-docs
python -m polymarket.research.local_lab.rearm_income_gate --run-income-tests
```
