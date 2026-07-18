# Revalidación cloud 2026-07-18 — Grind NIM BEST

**Estado:** revalidado en paper (feeds reales) · **no** es PnL on-chain  
**Entorno:** Cursor cloud agent · BTC spot via Binance.US fallback · NIM `nvidia/nemotron-mini-4b-instruct`  
**Protocolo:** 6 sesiones × 5.0 min · capitals 5 / 10 / 15 · estrategia congelada `grind_nim_best`  
**Live:** `POLY_LIVE_ARMED=0` · `POLY_LIVE_DRY_RUN=1` (sin órdenes reales)

Artefacto: `data_local/local_lab/grind_iterate/iterate_20260718_180113.json`  
Log: `data_local/local_lab/grind_iterate/revalidate_20260718_163103.log`

---

## Resultados

| Capital | WR traded | Wins/Losses | Total paper | Worst | ¿WR≥75%? |
|---------|-----------|-------------|-------------|-------|----------|
| **5 EUR** | **100%** | 5 / 0 | **+1.25** | 0.00 | **SÍ** |
| **10 EUR** | **50%** | 3 / 3 | **+0.04** | −0.28 | **NO** |
| **15 EUR** | **100%** | 5 / 0 | **+2.04** | 0.00 | **SÍ** |

### Detalle @5 EUR
`+0.32, +0.12, 0 (starve), +0.47, +0.22, +0.12`

### Detalle @10 EUR
`−0.07, +0.32, +0.12, −0.28, −0.12, +0.07`  
Pérdidas: el −0.28 superó el techo teórico `max_loss=0.10` (gap mid / flatten de ventana).

### Detalle @15 EUR
`+0.44, +0.76, +0.28, +0.20, +0.36, 0 (starve)`

---

## Lectura

1. El hito previo WR 80% @10 € **no se reprodujo** en esta ventana de mercado (WR 50%).
2. En **5 €** y **15 €** el método sí pasó fuerte (WR 100%, grind sin rojas).
3. Conclusión operativa: DNA útil, pero **aún no listo para inversión real** hasta recuperar WR≥75% estable @10 € (y dry-E2E).
4. Hardening aplicado tras esta ronda:
   - fallback BTC geo (Binance.com → Binance.US → Coinbase)
   - stops paper con mark ejecutable (bid/ask) + soft-cut 70% en grind
   - el iterador ya no sobrescribe `maker_demo_grind_nim_best.json` con snapshots 5/15

---

## WR-push post-hardening @10 EUR (2×6×5 min)

| Ronda | Mutación | WR traded | Total | Worst | ¿WR≥75%? |
|-------|----------|-----------|-------|-------|----------|
| 0 | base | 66.7% (4W/2L) | −0.10 | −0.43 | no |
| 1 | lock/loss 0.09 + mid 0.30–0.70 | 66.7% (2W/1L) | +0.35 | −0.05 | no |

Artefacto: `iterate_20260718_190325.json`  
**Conclusión:** aún **no** hay WR≥75% estable @10 € tras hardening. No armar live.

---

## Prep hacia micro-live (aún SAFE)

- Credenciales Relayer + CLOB + firma: OK (`prep_micro_live`)
- Config prep: `maker_demo_grind_nim_best_micro_live.json`
- **No armar** `POLY_LIVE_ARMED=1` hasta:
  1. WR≥75% @10 € en revalidación post-hardening
  2. Dry-E2E checklist OK
  3. Balance ≥ ~5 pUSD

---

## Comandos

```bash
# Revalidar DNA base @10€
SIM_NIM_MODEL=nvidia/nemotron-mini-4b-instruct \
python -m polymarket.research.local_lab.iterate_grind_wr \
  --rounds 2 --sessions 6 --minutes 5 \
  --strategies grind_nim_best --capitals 10 --no-early-stop

# Checklist (sin órdenes)
python -m polymarket.research.local_lab.prep_micro_live
```
