# Anti-colisión paralelo — teoría → implementación

## Fuentes (públicas / prestigiosas)
| Fuente | Idea aplicada |
|--------|----------------|
| Aussie Turtles — system diversification | Ensemble de **lógicas distintas** (pulse/follow), no N clones |
| D&T Systems — strategy PnL correlation | ρ≳0.8 ⇒ **una unidad de riesgo**; no sumar N× |
| ProfitLogic — portfolio heat | Veto central antes de orden (capa sobre estrategias) |
| MQL5 Part 7 — cross-pair filter | Bloquear misma dirección/mercado si ya hay claim |
| MarketMaker.cc — effective breadth | \(N_{eff}=N/(1+(N-1)\rho)\) para sizing |
| Horacle Capital — Polymarket framework | Maker + inventory skew; no latency race retail |

## Qué NO funciona
Correr el mismo DNA 4× en el mismo BTC 5m: colisión ~67%, ρ≈0.85 → PnL ≈1.15× no 4×.

## Qué implementamos
1. **`desk_coordinator`**: `mutex_market` | `window_slot` | `ensemble_role`
2. **`live_maker`**: claim antes de entrada; libera al cerrar
3. **Saldo ficticio dry**: `POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC` (libros CLOB reales)
4. **`sim_clob_desk`**: certificación **solo sim CLOB** (no paper), barra WR≥80% + PnL≥+1.50
5. **Scale config**: 25 USDC / 10 shares (más PnL, más riesgo controlado)

## Comando
```bash
export POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=1
export POLY_LIVE_DRY_VIRTUAL_BALANCE_USDC=50
python3 -m polymarket.research.local_lab.sim_clob_desk \
  --mode mutex_market --rounds 6 --minutes 8 --lines 2
```
