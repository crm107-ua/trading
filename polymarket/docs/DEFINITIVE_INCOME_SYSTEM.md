# Sistema definitivo de ingresos — Temperature Ladder

**Entrypoint único:**  
`python3 -m polymarket.research.local_lab.definitive_income_system`

**Estrategia canónica (research):** `config/weather_ladder_final_longterm.json`  
**Manga real micro:** `config/weather_ladder_definitive_real.json`  
**Manga high-income:** `config/weather_ladder_high_income.json` → [`HIGH_INCOME.md`](HIGH_INCOME.md)  
**Veredictos:** `DEFINITIVE_SYSTEM_CERTIFIED` → `REAL_INCOME_OPERABLE` → `REAL_INCOME_GO`

## Qué es “ultra perfecto” aquí

| Capa | Garantía |
|------|----------|
| DNA | Solo `press_under`, underdispersion, Beijing ≤0.50, wing-safe ≥28%/pierna |
| Research | `LONG_TERM_ROBUST` + `INCOME_WR80_POINT_ASSURED` + `INCOME_GENERATION_ASSURED` |
| Live | Cap según escala · sin smoke · abort parcial · SAFE al terminar |
| Post | Revalida basket/pierna/UD justo antes de FAK |

No grind, no copy viral, no tier `select`. Más PnL = **más tamaño**, no peores baskets.

## Comandos

```bash
# Estado (micro)
python3 -m polymarket.research.local_lab.definitive_income_system

# High income (~$200/semana esperado histórico con $100 deposit)
python3 -m polymarket.research.local_lab.definitive_income_system --scale high
python3 -m polymarket.research.local_lab.high_income_project

# Live high (región permitida + ≥$100)
POLY_LADDER_HIGH_INCOME=1 POLY_LADDER_REAL_CONFIRM=1 \
  python3 -m polymarket.research.local_lab.definitive_income_system \
    --scale high --income-loop --auto-execute --i-accept-real-loss YES \
    --rounds 40 --interval 180
```

## Checklist para ingreso real

1. Elegir escala y depositar (micro ≥$25 · high ≥$100 · aggressive ≥$200).
2. Región permitida (sin geoblock US).
3. Veredicto ≥ `REAL_INCOME_OPERABLE`.
4. Esperar edge press ≤0.50 (o income-loop en watch).
5. Confirm: `POLY_LADDER_REAL_CONFIRM=1` (+ `POLY_LADDER_HIGH_INCOME=1` si scale high).

## Evidencia congelada

- Long-term: 11/11 WR 100%, OOS 100%, sensibilidad/friction OK  
- Sim $25 → ~18.5× (hostil aún rentable)  
- Paper CLOB: 8/8 +$421  
- High size scale: ~5× micro weekly PnL a budget $25

Detalle: [`FINAL_LONGTERM_STRATEGY.md`](FINAL_LONGTERM_STRATEGY.md) · [`HIGH_INCOME.md`](HIGH_INCOME.md)
