# Por dónde seguir la investigación (hacia inversión real)

## Diagnóstico
| Bloqueo | Estado |
|---------|--------|
| Evidencia DNA | n≈11, Wilson≈0.74 → falta n≥50 / Wilson≥0.80 |
| Edge live | Libros caros (SH ~0.69); 0 hits forward |
| Capital | ~$3.45 no aguanta 1 miss |
| Ops | 3 procesos WATCH OK |

## Camino (en orden)
1. **Expandir histórico** (`expand_dna_evidence`) — misma DNA, más días pre-julio → subir n con honestidad (wins y losses).
2. **WATCH forward** — D+0/D+1/D+2, prioridad HK→BJ→SG→SH (hit-rate DNA + near-miss).
3. **No aflojar DNA** — basket 0.50 / leg 0.39 / UD.
4. **Capital** solo tras `rearm_income_gate=READY_TO_REARM`.

## Comando
```bash
PYTHONPATH=/var/www/html/trader python -m polymarket.research.local_lab.expand_dna_evidence --max-events 220
```

Artefacto: `vps_runs/DNA_EXPANSION_REPORT.json`
