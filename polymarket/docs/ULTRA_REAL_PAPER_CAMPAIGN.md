# Ultra-real paper campaign — Temperature Ladder v3

**Estrategia bloqueada:** `weather_ladder_champion_v2.json` / sim `weather_ladder_ultra_real_sim.json`  
**Estado:** `PAPER_INCOME_READY` · **live armado: NO** (`POLY_LIVE_ARMED=0`)

## Qué prueba (ultra-real)

1. **Walk-forward** sobre 90 casos cacheados con entry CLOB histórico  
   Friction: slip 1–3¢, fee 0–100 bps, fill 80–95%, min 5 shares, bankroll cronológico.
2. **Paper CLOB live** rediscovery + asks/history, con `max_per_city=3` y `sort_mode=horizon_first`  
   (evita que una sola ciudad se coma el capital — fallo detectado con HK-first).
3. **Income gate** exige research+friction **y** paper live (WR/PnL/friction base ≥0).

## Resultados campaña `campaign_20260809_235209`

### Walk-forward + friction ($150 →)

| Escenario | n | WR | PnL | Equity fin |
|-----------|---|----|-----|------------|
| base (slip 1¢, fill 95%) | 11 | 100% | **+$502.50** | $652.50 |
| slip 2¢ | 11 | 100% | +$442.77 | $592.77 |
| slip 3¢ + fee 50bps | 11 | 100% | +$372.33 | $522.33 |
| hostile fill 80% + fee 1% | 11 | 100% | +$371.58 | $521.58 |

Drawdown walk-forward base: **0%**.

### Paper CLOB (30d, caps ciudad)

- 9 trades resueltos · WR **77.8%** (7/2) · scorecard **+$230.48** · equity $150→$380
- Tras friction base: **+$190.53** (WR 77.8%, max DD ~12%)
- Stress slip 3¢+fee: aún **+$138.51**

### Gate

`PAPER_INCOME_READY` = true en todos los checks.  
`deploy_real_money` = **false** hasta dry-run live dedicado.

## Comando

```bash
python -m polymarket.research.local_lab.ultra_real_ladder_campaign
python -m polymarket.research.local_lab.weather_ladder_paper \
  --config polymarket/config/weather_ladder_ultra_real_sim.json
```

## Lectura operativa

- Esta es la **única** estrategia validada para escalar hacia dinero real.
- Paper positivo con fricción hostil ≠ garantía on-chain; el siguiente paso es micro dry-run (`DRY_RUN=1`, tope $10–25), no `ARMED=1` a ciegas.
- Mantener `max_per_city=3` y diversificar SG/SH/HK/Beijing.
