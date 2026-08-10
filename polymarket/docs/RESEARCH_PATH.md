# Por dónde seguir la investigación (hacia inversión real)

## Diagnóstico
| Bloqueo | Estado |
|---------|--------|
| Evidencia DNA | n≈11, Wilson≈0.74 → falta n≥50 / Wilson≥0.80 |
| Histórico pre‑julio | **CLOB prices-history vacío** → no fabricar cases viejos |
| Edge live | HK gap~4¢ pero **UD stuck** (ratio~2.7); BJ 2/3 espera basket |
| Capital | ~$3.45 no aguanta 1 miss |

## Camino (actualizado)
1. **Forward snapshots** — asks vivos (`quote_snapshots.jsonl`).
2. **`resolve_forward_cases`** — al cerrar: case DNA + `shadow_resolves.jsonl`.
3. **`assurance_research`** — scorecard Wilson path / UD stuck / dual-control / capital.
4. **WATCH** densificado cerca de DNA; scoreboard gates; Telegram 2/3.
5. **No aflojar DNA**. Capital solo con `READY_TO_REARM`.

## Comandos
```bash
python -m polymarket.research.local_lab.resolve_forward_cases
python -m polymarket.research.local_lab.assurance_research --write-docs
python -m polymarket.research.local_lab.verify_real_income_prep --write-docs
```

Artefactos: `ASSURANCE_SCORECARD.md` · `GATE_SCOREBOARD.json` · `FORWARD_PROGRESS.md` · `EVIDENCE_PROGRESS.json` · `shadow_resolves.jsonl`
