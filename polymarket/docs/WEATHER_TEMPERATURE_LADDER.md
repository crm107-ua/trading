# Temperature Ladder — Polymarket weather (paper)

**Fuente:** *Temperature ladder Polymarket bot* (Blockchain Surfer / @0xSurferX).

No intenta acertar el grado exacto. Compra un **cluster de 3–4 buckets adyacentes** centrado en el high de la **estación de resolución** (tras bias correction). Un winner a 100¢ cubre el resto del basket.

## Pipeline

1. Descubrir eventos `highest-temperature-in-{city}-on-{date}` (Gamma)
2. Forecast multi-modelo Open-Meteo en coords de estación (`stations.py`)
3. Truncar (no redondear) → centro del ladder
4. Probabilidades gaussianas por bucket + precios ask CLOB
5. Filtro EV (`calc_ev` / `ladder_ev`) + **underdispersion** (spread modelos vs típico)
6. Sizing por probabilidad (`size_ladder`), centro pesado, wings baratas
7. Paper fill a ask; settled si el evento ya resolvió, si no mark-to-mid

## Código

| Pieza | Ruta |
|-------|------|
| Math | `polymarket/src/weather/ladder.py` |
| Forecast | `polymarket/src/weather/forecast.py` |
| Markets | `polymarket/src/weather/markets.py` |
| Stations | `polymarket/src/weather/stations.py` |
| Paper | `polymarket/research/local_lab/weather_ladder_paper.py` |
| Config | `polymarket/config/weather_ladder.json` |
| vs Maker | `polymarket/research/local_lab/compare_ladder_vs_maker_paper.py` |

## Comandos

```bash
python -m polymarket.research.local_lab.weather_ladder_paper

NVIDIA_NIM_MODE=fast NVIDIA_NIM_CONTEXT_ENGINEERING=1 \
  python -m polymarket.research.local_lab.compare_ladder_vs_maker_paper --maker-minutes 5
```

## Guardrails (del artículo)

- Basket unitario barato (default `max_basket_cost=0.85`)
- 3–4 buckets, no 6–7
- Preferir ciudades volátiles + horizonte D+1/D+2
- Centrar en estación, no en “app del tiempo” de la ciudad
- Bias correction antes de construir el cluster


## Resolved paper (cómo imprime)

El edge del artículo se realiza en **resolución**, no en mark-to-mid.

1. Forecast histórico multi-modelo (estación) → centro truncado
2. Entry = precio CLOB pre-spike (`prices-history`)
3. Filtros artículo: basket ≤ 0.50, pierna máx ≤ 0.42, underdispersion
4. Settlement: winner 100¢ / losers 0

Ejemplo 2026-08-09 Shanghai: basket 0.185 → **+11.79 USDC** paper (WR 100% en esa corrida filtrada).
