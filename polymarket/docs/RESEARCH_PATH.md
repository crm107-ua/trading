# Por dónde seguir la investigación (hacia inversión real)

## Diagnóstico
| Bloqueo | Estado |
|---------|--------|
| Evidencia DNA | n≈11, Wilson≈0.74 → falta n≥50 / Wilson≥0.80 |
| Histórico pre‑julio | **CLOB prices-history vacío** → no fabricar cases viejos |
| Edge live | Libros caros; 0 hits DNA forward; HK gap~4–8¢ sin UD |
| Capital | ~$3.45 no aguanta 1 miss |

## Camino (actualizado)
1. **Forward snapshots** — cada round guarda asks vistos (`quote_snapshots.jsonl`).
2. **`resolve_forward_cases`** — al cerrar el mercado: snapshot→case→DNA take.
3. **WATCH** D+0/1/2, prioridad HK→BJ→SG→SH.
4. **Recheck ops** — +30s si gap≤8¢; **segundo +90s** si sigue ≤5¢ (DNA intacta).
5. **Gate scoreboard** — basket≤0.50 · leg≤0.39 · UD≤0.65; alerta Telegram en **2/3**.
6. **No aflojar DNA**. Capital solo con `READY_TO_REARM`.

## Comandos
```bash
python -m polymarket.research.local_lab.resolve_forward_cases
python -m polymarket.research.local_lab.research_telemetry
```

Artefactos: `telemetry/quote_snapshots.jsonl` · `GATE_SCOREBOARD.json` · `FORWARD_PROGRESS.md` · `EVIDENCE_PROGRESS.json`
