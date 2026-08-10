# Postura operativa — Temperature Ladder

## Decisión vigente: RESEARCH_ONLY

La ingeniería (gates DNA, VPS ES, fricción, Telegram, SAFE) puede estar lista.
La **evidencia** no lo está: n=11 DNA takes, Wilson95 lower ≈0.74.

### No hacer
- No depositar capital adicional solo por el Monte Carlo / WR puntual 100%.
- No tratar el bootstrap MC como validación OOS independiente.
- No forzar near-miss ni aflojar DNA.
- No martingale tras un miss.

### Sí hacer
- Mantener vigilante DNA-gated en SAFE / política actual.
- Acumular takes (paper + DNA hits) hasta **n≥30** (ideal **≥50**) antes de hablar de depósito.
- Recalcular Wilson95 lower en cada nuevo take; ignorar WR puntual con n pequeño.
- Regenerar: `python3 -m polymarket.research.local_lab.ladder_viability_report --balance … --write-docs`

### Umbrales
| Gate | Mínimo |
|------|-------:|
| Hablar de depósito | n≥30 y Wilson≥0.80 |
| GO_MICRO | n≥50 y Wilson≥0.80 + capital aguanta ≥1 miss |

## Ahora en VPS
**WATCH_ONLY** — EDGE avisa por Telegram, **no posta**.

Tres procesos investigación: `ladder-private-manager` · `ladder-progress-watch` · `ladder-research-improve`.

Rearme dinero real solo con `rearm_income_gate` = `READY_TO_REARM` + `POLY_LADDER_ALLOW_REARM=1`.

Ver [`PROFESSIONAL_PREP.md`](PROFESSIONAL_PREP.md) · [`PREPARE_REAL_MONEY.md`](PREPARE_REAL_MONEY.md) · [`REARM_INCOME_GATE.md`](REARM_INCOME_GATE.md).
