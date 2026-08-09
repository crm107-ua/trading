# Winning Desk v2 — estrategia paper ganadora (investigación)

**Estado:** paper lab · **no** on-chain · no proyección anual  
**Fecha:** 2026-08-09 · dataset **90** mercados resueltos

## Por qué esta y no las anteriores

| Pieza | Qué aprendimos | Decisión |
|-------|----------------|----------|
| Temperature Ladder (SurferX) | Edge en **resolución** con basket barato | Sleeve primario |
| Seoul / volumen flojo | Seoul 0%; basket≤0.65 **overfit** (WR~44% al ampliar Shanghai) | Excluir |
| Research IS/OOS 90 casos | basket≤0.50 · pierna≤0.39 · min_p=0.35 · bias+0.5 | Congelado |
| Universo | SG + Shanghai + Hong Kong (HK 1 trade) | Incluir |
| **Tier press_under** | Mismos filtros + underdispersion (press size) | Primero |
| **Tier select** | Mismos filtros sin exigir under | Si skip |
| grind_nim_best | Micro histórico | Solo idle capital |

## Reglas operativas

1. D+1/D+2 en SG / Shanghai / HK si pasa filtros.
2. Entry: ask live o CLOB pre-spike (replay).
3. Settlement: winner 100¢.
4. Maker solo con capital sobrante.
5. Nunca live sin `POLY_LIVE_ARMED` + gate.

## Evidencia (90 cases)

- Full: WR **1.00** (6/6), PnL **+$218.18**, PF **10**
- OOS half: WR **1.00** (3/3), PnL **+$72.39**
- Verdict: **STRONG**
- Artifact: `data_local/local_lab/weather_research/research_20260809_221452.json`
- Config: `config/weather_ladder_champion_v2.json`

## Comandos

```bash
python -m polymarket.research.local_lab.validate_two_tier
python -m polymarket.research.local_lab.research_winning_edge --max-events 90
python -m polymarket.research.local_lab.winning_desk --maker-rounds 0
python -m polymarket.research.local_lab.weather_ladder_paper \
  --config polymarket/config/weather_ladder_champion_v2.json
```
