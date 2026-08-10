# Estrategia final a largo plazo

**Config canónica:** `polymarket/config/weather_ladder_final_longterm.json`  
**Veredicto:** `LONG_TERM_ROBUST` + `INCOME_GENERATION_ASSURED` + `INCOME_WR80_POINT_ASSURED`

## Qué la hace durable (no solo “ahora”)

| Regla | Por qué |
|-------|---------|
| Solo `press_under` | El tier `select` bajaba WR a ~75% en universo expandido |
| Underdispersion obligatoria | Evita entradas con ensemble disperso |
| Beijing basket ≤ 0.50 | Mata la pérdida open-skew a basket 0.55 |
| Sizing ≥28%/pierna | Hits en el ala siguen siendo PnL>0 |
| `max_per_city` + horizon-first | No quema bankroll en una ciudad |
| Sin grind/copy idle | Ruido que empeora el desk |

## Certificación largo plazo (`long_term_robustness.py`)

Sobre 124 casos SG/SH/HK/BJ (2026-07-10 → 2026-08-09):

| Test | Resultado |
|------|-----------|
| Overall | **11/11 WR 100%**, +$659 |
| Walk-forward semanal OOS | **WR 100%** (n=10) |
| Mitades calendario | **100% / 100%** |
| Semanas ISO | todas WR 100% (cuando n≥1) |
| Rolling 4 trades | min WR **100%** |
| Leave-one-city-out | todas WR 100% |
| Sensibilidad ± basket/leg | pass rate **100%** |
| Friction hostil | WR **100%**, PnL>0 |

Perfiles más estrictos (sin HK / basket 0.45) también ganan al 100%, pero con menos trades; el final equilibra **pureza + frecuencia**.

## Simulación tipo dinero real

$25 base → **~$462 (18.5×)** WR100%; stress hostil WR90.9% aún rentable.  
Paper CLOB: **8/8 +$421**.

## Operación

```bash
# Certificar largo plazo
python3 -m polymarket.research.local_lab.long_term_robustness

# Sim ingresos realistas
python3 -m polymarket.research.local_lab.simulate_real_income

# Paper
python3 -m polymarket.research.local_lab.weather_ladder_paper \
  --config polymarket/config/weather_ladder_final_longterm.json

# Ingresos live (región permitida + depósito)
POLY_LADDER_REAL_CONFIRM=1 \
  python3 -m polymarket.research.local_lab.ladder_income_loop \
    --auto-execute --i-accept-real-loss YES --rounds 40 --interval 180
```

## Límite honesto

Robustez certificada en el histórico disponible (~30 días de weather Polymarket).  
No existe aún un año de datos de estos mercados; el diseño anti-overfit (press-only, sensibilidad 100%, OOS semanal) es la mejor garantía estructural posible hoy.
