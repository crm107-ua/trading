# Winning Desk v1 — estrategia paper ganadora (investigación)

**Estado:** paper lab · **no** on-chain · no proyección anual  
**Fecha:** 2026-08-09

## Por qué esta y no las anteriores

| Pieza | Qué aprendimos | Decisión |
|-------|----------------|----------|
| Temperature Ladder (SurferX) | Edge real en **resolución** con basket barato | Sleeve primario |
| Sweep 50 días resueltos | **Singapore WR 100% (+131$)**; SG+Shanghai **WR 80% (+157$ / 10)**; Seoul **0% (−24$)** | Solo SG + Shanghai |
| Bias estación | `bias_c=+0.5` mejora centro truncado | Congelado en stations + config |
| Filtros | basket ≤0.50, pierna ≤0.39, width=3, budget=12 | `weather_ladder_champion.json` |
| grind_nim_best | Campeón histórico WR≥75% micro | Sleeve secundario con capital idle |
| Context Engineering | Mejor plumbing NIM, no edge solo | On en maker hybrid |

## Reglas operativas

1. **Ladder primero** en D+1/D+2 Singapore/Shanghai si pasa EV + precio.
2. Entry paper: ask live (open) o CLOB pre-spike (resolved replay).
3. Settlement: winner 100¢.
4. **Maker** solo con capital sobrante (`grind_nim_best`, NIM hybrid + nemotron-mini).
5. Nunca Seoul en weather. Nunca live sin `POLY_LIVE_ARMED` + gate.

## Comandos

```bash
# Research / re-optimizar
python -m polymarket.research.local_lab.optimize_weather_ladder --max-events 50

# Desk ganador
python -m polymarket.research.local_lab.winning_desk --maker-rounds 3 --maker-minutes 5

# Solo ladder campeón
python -m polymarket.research.local_lab.weather_ladder_paper \
  --config polymarket/config/weather_ladder_champion.json
```

## Evidencia congelada

- Optimize artifact: `data_local/local_lab/weather_optimize/optimize_*.json` (50 resolved cases)
- Post-filter SG+Shanghai (loose): WR **0.80**, PnL **+$157.23**, n=10
- **Champion final (SG+SH + underdispersion):** WR **1.00** (5/5), PnL **+$123.94**, PF **10.0**
- Singapore alone: WR **1.00**, PnL **+$131.41**, n=5
- Live paper scorecard (resolved sleeve): **+$37.43** (session equity ~+$34.7 con open mark)
- Winning desk combo sample: ladder + maker sleeves → **+$25.45** combined (pre-final under filter)
