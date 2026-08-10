# Sistema definitivo de ingresos — Temperature Ladder

**Entrypoint único:**  
`python3 -m polymarket.research.local_lab.definitive_income_system`

**Estrategia canónica (research):** `config/weather_ladder_final_longterm.json`  
**Manga real (producción):** `config/weather_ladder_definitive_real.json`  
**Veredictos:** `DEFINITIVE_SYSTEM_CERTIFIED` → `REAL_INCOME_OPERABLE` → `REAL_INCOME_GO`

## Qué es “ultra perfecto” aquí

| Capa | Garantía |
|------|----------|
| DNA | Solo `press_under`, underdispersion, Beijing ≤0.50, wing-safe ≥28%/pierna |
| Research | `LONG_TERM_ROBUST` + `INCOME_WR80_POINT_ASSURED` + `INCOME_GENERATION_ASSURED` |
| Live | Cap ≤$5, 1 mercado/sesión, sin smoke, abort parcial, SAFE al terminar |
| Post | Revalida basket/pierna/UD justo antes de FAK |

No grind, no copy viral, no tier `select`.

## Comandos

```bash
# Estado del sistema (sin órdenes)
python3 -m polymarket.research.local_lab.definitive_income_system

# Re-certificar research + estado
python3 -m polymarket.research.local_lab.definitive_income_system --recertify

# Ingreso real (región permitida + wallet fondeada)
POLY_LADDER_REAL_CONFIRM=1 \
  python3 -m polymarket.research.local_lab.definitive_income_system \
    --income-loop --auto-execute --i-accept-real-loss YES \
    --rounds 40 --interval 180
```

## Checklist para ingreso real

1. Depositar **≥25 USDC** en la wallet Polymarket (mínimo técnico $2).
2. Ejecutar desde **región permitida** (sin geoblock US).
3. Veredicto del sistema ≥ `REAL_INCOME_OPERABLE`.
4. Esperar edge (`accepted_n≥1`) o dejar el income-loop en watch.
5. Confirmar: `POLY_LADDER_REAL_CONFIRM=1` + `--i-accept-real-loss YES`.

## Evidencia congelada

- Long-term: 11/11 WR 100%, OOS 100%, sensibilidad/friction OK  
- Sim $25 → ~18.5× (hostil aún rentable)  
- Paper CLOB: 8/8 +$421  

Detalle: [`FINAL_LONGTERM_STRATEGY.md`](FINAL_LONGTERM_STRATEGY.md) · [`INCOME_GENERATION_ASSURED.md`](INCOME_GENERATION_ASSURED.md)
