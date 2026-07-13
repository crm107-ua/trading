# Ideación adversarial — Polymarket (2026-07-13)

**Modo:** papel · sin optimización · ~1 h · cero máquina de validación.

**Contexto:** artículo Polymarket bots — 5 familias de ejecución. Restricciones: retail USDC ~10k, sin colocation, latencia Binance ~236 ms p50, fees taker ~2%.

**Umbral supervivencia:** edge bruto esperado ≥ **2× fricción** del ciclo (lección #14).

---

## Resultado

| Métrica | Valor |
|---------|-------|
| Familias evaluadas | 5 |
| Supervivientes | **1** (#15 stale-quote / direccional cubierta) |
| Elegida para pre-reg | **Familia 2** — fair value vs CLOB stale |

---

## Las cinco familias (artículo)

| # | Familia | Mecanismo | Puerta de muerte en papel |
|---|---------|-----------|---------------------------|
| 1 | Arbitraje temporal | Up+Down en momentos distintos cuando suma < 1 | **Pierna incompleta** — segunda pata falla >Y%; fricción 2× taker en dos patas |
| 2 | Direccional cubierta (stale-quote) | Fair value desde spot vs strike; entrar si net_edge > umbral | **Latencia + feed stale** — si p95 spot→ejecución > ventana 5m edge; **superviviente condicional** |
| 3 | Market making inventario | Spread bid/ask multi-mercado | **Complejidad + capital** — inventario skew; competencia makers $50k/mes |
| 4 | Captura pre-resolución | Comprar 98–99¢ cerca cierre | **Tail** — resolución disputada; payoff acotado pero cola operativa |
| 5 | Rotación dinámica 5m/15m | Cambiar ventana según spread | **Complejidad** — dos regímenes; latencia multiplica errores |

---

## Familia 2 — por qué supervive (condicional)

**Mecanismo (2 frases):** el CLOB actualiza más lento que spot BTC; cuando el precio Up/Down no refleja el movimiento externo, hay edge ejecutable tras fees y slippage. Quién pierde: makers con quotes obsoletas.

| A favor | En contra |
|---------|-----------|
| Causal simple, medible | Mid-only backtest sesga al alza |
| Una pata (no arb incompleto) | Binance RTT ~236 ms vs bots colocados |
| Alineado con Fase 0 GO | Edge puede ser < 2× fricción → muerte D-1 |

**Condición:** si screen con slippage honesto falla D-1 o D-2 → **MUERTA** sin iterar umbrales.

---

## Familias muertas en papel (resumen)

- **#1:** muerte por pierna incompleta + doble taker fee — misma clase que arb temporal del artículo §6.
- **#3:** muerte por complejidad/capital — retail 10k no compite en inventario multi-mercado.
- **#4:** muerte por tail/resolución — sin condición numérica honesta pre-data.
- **#5:** muerte por complejidad — rotación dinámica = dos hipótesis, no una.

---

## Decisión para registry

| Acción | Detalle |
|--------|---------|
| Abrir **#15** | Solo familia 2 — stale-quote / fair-value executable edge |
| No implementar | Familias 1, 3, 4, 5 en este intento |
| Pre-reg | `docs/PREREG_15_POLY_STALE_QUOTE.md` antes de screen |

---

*Sesión adversarial Polymarket. Genera candidato único para pre-reg #15.*
