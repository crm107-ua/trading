# Decisión go-live (2026-07-19) — feedback final simulación

## Confrontación Shadow OFIR vs Pulse (paper, mercado real)

| DNA | Cap | WR decisivo | Decisive | PnL robusto | ¿Lista dinero real? |
|-----|-----|-------------|----------|-------------|---------------------|
| **promo_pulse_c10** | 10 | **87.5%** | 32 | **+2.37** | **SÍ — micro** |
| promo_shadow_c10 | 10 | 100%* | 3 | +0.15 | NO (n&lt;4) |
| promo_shadow_c5 | 5 | 63.6% | 11 | +0.24 | NO |
| promo_pulse_c5 | 5 | 62.3% | 53 | +1.58 | NO (dip de régimen) |

\*muestra insuficiente.

Gate dual `READY_STRICT`: **NO** (falla @5).  
`@10` solo: WR75 + paralelo70 en verde.

## Shadow OFIR (añadido al catálogo)
Stack desk privado 2026 (síntesis, no leak): latency lead + toxicity imbalance + mid-lag + blackout.
- Código: `maker_shadow_ofir` / `fusion_enable_shadow`
- Configs: `maker_demo_promo_shadow_c5.json`, `maker_demo_promo_shadow_c10.json`
- Cuando llena @10 va limpio (3W/0L) pero aún poco volumen → experimental

## Veredicto definitivo
**La única estrategia lista para inversión real ahora es `maker_demo_promo_pulse_c10.json` (@10), en modo micro.**

Secuencia:
1. `POLY_LIVE_ARMED=1` `POLY_LIVE_DRY_RUN=1` `MAX_CAPITAL=5` — dry CLOB
2. Si dry sano: `DRY_RUN=0` con `MAX_CAPITAL=2..5` (no 10 de entrada)
3. No armar @5 ni Shadow hasta WR≥75% fresco decisive≥8

Live debe permanecer SAFE salvo armado explícito.
