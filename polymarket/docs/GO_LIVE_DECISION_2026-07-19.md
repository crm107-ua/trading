# Decisión go-live (2026-07-19) — feedback simulación realista

## Qué se comparó (paper, feeds/CLOB reales, dinero simulado)
| DNA | Capital | WR decisivo (3h) | Decisive | PnL robusto | Estado |
|-----|---------|------------------|----------|-------------|--------|
| **promo_pulse_c10** | 10 | **~87%** | 31 | +2.21 | **LISTO micro real** |
| promo_pulse_c5 | 5 | ~64% | 39 | +1.76 | NO (regime dip) |
| promo_shadow_c5 | 5 | 100%* | 2 | +0.26 | Experimental (n bajo) |
| promo_shadow_c10 | 10 | n/a | 0 | 0 | Starve / no operativo aún |

\*muestra insuficiente (decisive < 4).

## Shadow OFIR (método “desk privado”)
Síntesis (no leak de un bot concreto): latency lead + toxicity imbalance + mid-lag guard + blackout settlement.
Código: `maker_shadow_ofir` + configs `promo_shadow_c5/c10`. Catálogo FEATURED.
Aún no supera a Pulse en operatividad; cuando llena, va limpio (2W/0L @5).

## Veredicto definitivo para dinero real
1. **Única lista ahora: `maker_demo_promo_pulse_c10.json` @10€**  
   - Gate fresco: WR75 + paralelo70 @10 en verde  
   - Empezar: dry-run → `DRY_RUN=0` con `MAX_CAPITAL≤5` (micro), no 10 de golpe
2. **@5 Pulse: NO armar** hasta recuperar WR≥75% fresco (tight restore en curso)
3. **Shadow: NO armar** hasta decisive≥8 y WR≥75% en paralelo

## Secuencia operador
```bash
python3 -m polymarket.research.local_lab.go_live_arm_check
# Solo si READY_* y DNA=@10 pulse:
# ARMED=1 DRY_RUN=1 → dry
# luego DRY_RUN=0 MAX_CAPITAL=2..5
```
Live flags deben volver a SAFE tras pruebas.
