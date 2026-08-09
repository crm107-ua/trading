# Winning Desk v2 — estrategia paper ganadora (investigación)

**Estado:** paper lab · **no** on-chain · no proyección anual  
**Fecha:** 2026-08-09

## Por qué esta y no las anteriores

| Pieza | Qué aprendimos | Decisión |
|-------|----------------|----------|
| Temperature Ladder (SurferX) | Edge real en **resolución** con basket barato | Sleeve primario |
| Sweep 50 días resueltos | **Singapore** fuerte; Seoul **0%** | Solo SG + Shanghai |
| Bias estación | `bias_c=+0.5` mejora centro truncado | Congelado en stations |
| **Tier core** | underdispersion + basket≤0.50 + pierna≤0.39 | WR **100%** (5/5), +**$182** |
| **Tier volume** | basket≤0.65 + pierna≤0.45 + bias_override+0.5 | WR **85.7%** (6/7), +**$270**, OOS WR **75%** |
| grind_nim_best | Campeón histórico WR≥75% micro | Sleeve secundario idle |
| Context Engineering | Mejor plumbing NIM, no edge solo | On en maker hybrid |

## Reglas operativas

1. **Ladder dos niveles** en D+1/D+2 Singapore/Shanghai:
   - Primero `core_under` (máxima convicción / press).
   - Si skip → `volume_bias` (más oportunidades, aún EV+).
2. Entry paper: ask live (open) o CLOB pre-spike (resolved replay).
3. Settlement: winner 100¢.
4. **Maker** solo con capital sobrante (`grind_nim_best`).
5. Nunca Seoul. Nunca live sin `POLY_LIVE_ARMED` + gate.

## Comandos

```bash
# Validar edge dos niveles (offline sobre cases.json)
python -m polymarket.research.local_lab.validate_two_tier
python -m polymarket.research.local_lab.kfold_champion

# Research / ampliar dataset
python -m polymarket.research.local_lab.research_winning_edge --max-events 100

# Desk ganador
python -m polymarket.research.local_lab.winning_desk --maker-rounds 2 --maker-minutes 4

# Solo ladder campeón v2
python -m polymarket.research.local_lab.weather_ladder_paper \
  --config polymarket/config/weather_ladder_champion_v2.json
```

## Evidencia congelada

- Cases: `data_local/local_lab/weather_optimize/cases.json` (50 resolved)
- Core underdispersion: WR **1.00**, PnL **+$182.45**, n=5, OOS half WR **1.00**
- Volume bias: WR **0.857**, PnL **+$269.60**, n=7, OOS half WR **0.75** (+$77)
- **Two-tier union:** WR **0.889** (8/9), PnL **+$237.78**, OOS half WR **1.00** (5/5, +$85)
- K-fold champion (core): verdict **STRONG**
- Live paper scorecard (resolved sleeve): **+$53.16**
- Config: `config/weather_ladder_champion_v2.json` (tiers) + pointer en `weather_ladder_champion.json`
