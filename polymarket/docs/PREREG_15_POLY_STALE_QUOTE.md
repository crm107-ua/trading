# Pre-registro #15 — Polymarket Stale-Quote / Fair-Value Executable Edge

**Congelado:** 2026-07-13 — **antes de screen, backtest o lectura de resultados.**  
**Fase 0:** `docs/POLYMARKET_FEASIBILITY.md` (GO condicionado).  
**Ideación:** `research/ideation_poly_2026.md` (familia 2 única superviviente).

**Mecanismo (vinculante):** el CLOB de Polymarket actualiza más lento que el precio spot de BTC; el bot opera cuando el precio del outcome (Up) no refleja aún el movimiento externo, cobrando el ajuste. Quién pierde: makers con órdenes límite obsoletas y traders lentos.

---

## Decisiones congeladas

| Tema | Decisión |
|------|----------|
| **Familia** | Solo direccional cubierta / stale-quote — **no** arb temporal multi-pata |
| **Universo** | Mercados activos `Bitcoin Up or Down` ventana **5m** (15m excluido en #15) |
| **Motor** | Simulador `research/poly_lab/sim_stale_quote.py` — **no** Freqtrade |
| **Capital referencia** | **10 000 USDC** |
| **Presupuesto** | **≤ 6 h/semana**, cierre **2026-08-31** |
| **Runs** | **Un solo** screen — sin hyperopt de umbrales |

---

## Pricing (parámetros fijos)

| Parámetro | Valor | Notas |
|-----------|-------|-------|
| `sigma_annual` | **0.55** | Vol anualizada fija — no optimizar |
| `min_net_edge` | **0.02** | 2¢ por share tras costes |
| `safety_buffer` | **0.005** | Colchón adicional |
| `taker_fee` | **0.02** | 2% Polymarket taker |
| `maker_fee` | **0.00** | No usado en #15 |
| `slippage_per_100_shares` | **0.003** | Escalón VWAP conservador |

Fair value:

```
P_up = Φ( (spot - strike) / (σ × √(time_remaining_years)) )
```

---

## Ejecución

| Modo | Elección |
|------|----------|
| Tipo orden | **Taker FAK** únicamente |
| Post-only | **Prohibido** en #15 |
| Tamaño máx | **500 USDC** por ventana |
| Kelly | **0.15** fracción sobre edge estimado |

---

## Costes (executable edge)

```
edge_bruto = fair_up - vwap_ask(size)
net_edge = edge_bruto - taker_fee - spread_half - slippage_est - safety_buffer
```

Entrar solo si `net_edge > min_net_edge`.

---

## Riesgo

| Límite | Valor |
|--------|-------|
| `max_inventory_skew` | 0.25 (fracción bankroll en una dirección) |
| `max_usd_per_window` | 500 |
| `kill_switch_feed_stale_ms` | 5000 |
| Pierna incompleta | N/A (una pata) — reportar `fill_rate` |

---

## Condiciones de muerte (pre-escritas)

| ID | Condición | Umbral |
|----|-----------|--------|
| **D-1** | Edge acumulado < 2× fricción acumulada | `net_edge_sum < 2 * friction_sum` |
| **D-2** | Latencia p95 spot→sim fill | > **3000 ms** |
| **D-3** | Concentración PnL en una ventana | > **40%** PnL neto en un solo mercado |
| **D-4** | Fill rate | < **50%** de órdenes simuladas |
| **D-5** | Sharpe OOS (mitad temporal 2) | < **0.5** |

Cualquier D dispara → **MUERTA** sin apelación.

---

## Validación (un run)

| Bloque | Detalle |
|--------|---------|
| Split | IS: primera mitad temporal · OOS: segunda mitad |
| Datos | `prices-history` mid + slippage conservador; depth WS si disponible |
| Artefacto | `research/output/poly_15/<run_id>/report.json` |
| Veredicto | **PASA** solo si ningún D dispara **y** PnL neto OOS > 0 |

---

## Techo económico (10k USDC)

| Supuesto | Orden magnitud |
|----------|----------------|
| Trades/día retail | 5–20 ventanas operables |
| Edge neto/trade | 0,5–2¢ × tamaño |
| Neto anual optimista | **200–800 USDC/año** |
| Equivalencia laboral | **6–15 h facturadas** en escenario bueno |

El presupuesto 6 h/semana justifica **prueba de mecanismo**, no negocio a escala 10k.

---

*Congelado. Prohibido ajustar likelihoods, σ, min_net_edge o slippage tras ver PnL.*
