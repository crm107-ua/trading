# Por dónde seguir la investigación (hacia inversión real)

## Diagnóstico
| Bloqueo | Estado |
|---------|--------|
| Evidencia DNA | n≈11, Wilson≈0.74 → falta n≥50 / Wilson≥0.80 |
| Histórico pre‑julio | **CLOB prices-history vacío** → no fabricar cases viejos |
| Edge live | Libros caros (SH ~0.69, HK ~0.57); 0 hits DNA forward |
| Capital | ~$3.45 no aguanta 1 miss |

## Camino (actualizado)
1. **Forward snapshots** — cada round guarda asks vistos (`quote_snapshots.jsonl`).
2. **`resolve_forward_cases`** — al cerrar el mercado: snapshot→case→DNA take.
3. **WATCH** D+0/1/2, prioridad HK→BJ→SG→SH, recheck ≤8¢.
4. **No aflojar DNA**. Capital solo con `READY_TO_REARM`.

## Comandos
```bash
python -m polymarket.research.local_lab.resolve_forward_cases
```

Artefactos: `telemetry/quote_snapshots.jsonl` · `FORWARD_RESOLVE_REPORT.json` · `EVIDENCE_PROGRESS.json`
