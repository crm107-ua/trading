# Polymarket Lab — mapa de arquitectura (artículo → capas)

**Propósito:** referencia estructurada del diseño de bots Polymarket (BTC Up/Down 5m/15m). **No** es estrategia lista para copiar.

---

## Seis capas (orden de ejecución)

| Capa | Módulo conceptual | Entrada | Salida |
|------|-------------------|---------|--------|
| 1 — Data | feeds externos + CLOB WS + Gamma | APIs | `market_state` |
| 2 — Signals | `build_market_features` | `market_state` | features (imbalance, momentum, time_remaining) |
| 3 — Pricing | `estimate_fair_values` + `find_executable_edge` | features + rules | fair Up/Down, `net_edge` |
| 4 — Position | `choose_position_structure` | opportunity | plan direccional o hedge |
| 5 — Execution | `build_execution_plan` | plan | órdenes GTC/FOK/FAK |
| 6 — Risk | `risk_manager_approves` | order_plan | bool + límites |

**Regla vinculante:** el loop live (`src/bot.py`) ejecuta lógica predefinida; la IA solo en capa research.

---

## Cinco familias de PnL (artículo) — no combinar

| # | Familia | Mecanismo | Riesgo principal |
|---|---------|-----------|------------------|
| 1 | Arbitraje temporal | Comprar Up+Down en momentos distintos cuando suma < 1 | Pierna incompleta |
| 2 | Direccional cubierta | Fair value vs CLOB; hedge parcial | Feed stale |
| 3 | Market making inventario | Spread bid/ask multi-mercado | Inventario skew |
| 4 | Captura pre-resolución | Comprar 98–99¢ cerca del cierre | Tail / resolución |
| 5 | Rotación dinámica | Cambiar entre ventanas 5m/15m | Complejidad + latencia |

**#15 elige solo familia 2** (*stale-quote / fair-value executable edge*).

---

## Fórmulas como spec (congeladas en pre-reg)

### Fair value simplificado

```
P(Up) = Φ( (spot - strike) / (σ × √(time_remaining)) )
```

- `strike`: precio BTC al inicio de la ventana (fuente de resolución Polymarket)
- `σ`: volatilidad anualizada fija (pre-reg), no optimizada post-hoc
- `Φ`: CDF normal estándar

### Executable edge

```
edge_bruto = fair_value - ask_price   # compra Up
net_edge = edge_bruto - taker_fee - spread_half - slippage_est - safety_buffer
```

Entrar solo si `net_edge > min_net_edge` (umbral fijo en pre-reg).

### PnL descompuesto (simulador)

| Componente | Significado |
|------------|-------------|
| `edge_bruto` | Diferencia fair vs ejecución |
| `resolution_pnl` | PnL al settle (0 o 1) |
| `friction` | fees + slippage + spread |
| `account_return` | PnL neto / bankroll USDC total |

---

## Flujo del bot (pseudocódigo)

```python
while True:
    market_state = await receive_market_data()
    features = build_market_features(market_state)
    fair_values = estimate_fair_values(market_state, features)
    opportunity = find_executable_edge(market_state, fair_values)
    if opportunity is None:
        continue
    position_plan = choose_position_structure(market_state, opportunity)
    order_plan = build_execution_plan(market_state, position_plan)
    if risk_manager_approves(market_state, order_plan):
        await submit_orders(order_plan)
```

---

## Datos y limitaciones conocidas

| Fuente | Qué da | Qué NO da |
|--------|--------|-----------|
| Gamma API | metadata, token_ids, strike, end_time | depth |
| CLOB REST `/book` | depth actual | histórico |
| CLOB `/prices-history` | mid series | depth, bid/ask |
| CLOB WS `market` | book snapshots live | replay sin grabar |

**Producción seria:** mínimo 30 días de depth propio (`clob_recorder`) antes de GO-live.

---

## Relación con el lab Binance

| Binance (#1–#14) | Polymarket (#15+) |
|------------------|-------------------|
| Freqtrade | APIs directas |
| spot/perp USDT | USDC prediction markets |
| funding carry, momentum | stale-quote fair value |

Ver [`POLYMARKET_FEASIBILITY.md`](POLYMARKET_FEASIBILITY.md) y [`PREREG_15_POLY_STALE_QUOTE.md`](PREREG_15_POLY_STALE_QUOTE.md).
