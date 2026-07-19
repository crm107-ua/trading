# Micro 2€ compound — camino más seguro (pionero)

## Por qué este camino (vs scale/paralelo)
| | Micro 2€ 1 línea | Scale 25€ / paralelo |
|--|------------------|----------------------|
| Colisión | **0** | ρ≈0.85 |
| Capital | **2.5€** práctico (2€ solo si mid≲0.40) → acumula a 5€ | exige 25€+ |
| Riesgo | kill racha + DD 1€ | desk heat alto |
| PnL/trade | pequeño pero **compuesto** | grande e inestable |
| Floor CLOB | 5sh×px ≤ capital (SKIP si no cabe) | holgado |

## Reglas
1. **Solo 1 línea** `maker_fusion` / pulse
2. Reinvertir wins; cooldown 1 ronda tras loss
3. Halt: 2 losses seguidos o DD≥1€ desde pico o bank&lt;1.25€
4. `cheap_side_only` + `max_quote_mid≈0.48` para caber en 2€

## Sim (CLOB real, dinero ficticio)
```bash
python3 -m polymarket.research.local_lab.sim_micro_compound \
  --start 2.5 --rounds 10 --minutes 6
```

> Con exactamente 2.00€ muchas ventanas BTC 5m tienen mid>0.40 → starve.
> **2.5€** es el micro operable realista (sigue siendo “1–2€ zone”).

## Real (solo tras MICRO2_CERTIFIED)
```bash
export POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=1 POLY_LIVE_MAX_CAPITAL_USDC=2.5
# dry 30–45m…
export POLY_LIVE_DRY_RUN=0   # misma config micro2
export POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1  # SAFE
```
