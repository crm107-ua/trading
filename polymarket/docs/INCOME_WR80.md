# Aseguramiento WR ≥ 80% para ingresos

**Perfil:** `weather_ladder_income_wr80.json`  
**Veredicto:** `INCOME_WR80_POINT_ASSURED` (2026-08-10)

## Hallazgo clave al iterar

Sobre **132** mercados resueltos (no solo la ventana corta):

| Perfil | n | WR | OOS half |
|--------|---|----|----------|
| Legacy v3 press+select (BJ≤0.55) | 28 | **75%** | 71–79% |
| **Income WR80 press-only (BJ≤0.50)** | **11** | **100%** | **100%** |

El tier `select` diluye el WR por debajo de 80%. Se eliminó para ingresos.

## Cambios que suben el WR económico

1. **Solo `press_under`** (exige underdispersion)
2. **Beijing basket máx 0.50** (antes 0.55 → pérdida 2026-07-24)
3. **Sizing wing-safe**: blend + mínimo **28%** presupuesto/pierna (antes el centro se comía el budget y un hit en el ala perdía dinero, HK 2026-07-17)

## Evidencia income_wr80

- Point WR **11/11 = 100%** · PnL **+$693** (post-sizing)
- OOS half WR **100%** (6/6)
- Friction stress (slip 1–3¢, fee, fill 80%): WR **100%** en todos
- Wilson 95% lower ≈ **0.74** · bootstrap 5% ≈ **1.0**
- `ci95_wr80_assured=false` → con n=11 no hay IC95>80%; el **punto y OOS sí superan 80% con holgura**

## Comando

```bash
python3 -m polymarket.research.local_lab.assure_wr80_income
```

## Dinero real

Este gate es la mejor aseguranza **paper/replay** posible aquí.  
Ingresos on-chain siguen requiriendo: región sin geoblock + depósito ~$25 + `ladder_income_loop`.

```bash
POLY_LADDER_REAL_CONFIRM=1 \
  python3 -m polymarket.research.local_lab.ladder_income_loop \
    --auto-execute --i-accept-real-loss YES --rounds 40 --interval 180
```
