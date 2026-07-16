# Hito 2026-07-16 — Maker Edge $100 (lab → simulación real-feed)

**Estado:** HITO DE LABORATORIO CONSEGUIDO · **no** es PnL on-chain  
**Hipótesis:** #16 maker stale-quote (familia) + estrategia local `maker_edge`  
**Capital de referencia lab:** 100 USD  
**Fecha:** 2026-07-16  

---

## 1. Objetivo del hito

| Criterio | Umbral | Resultado |
|----------|--------|-----------|
| Win rate (sesiones con fills, net>0) | ≥ 75% | **75%** (margin_max_v3) |
| Avg net / sesión | ≥ +12 USD (subido desde céntimos) | **+15,27 USD** |
| Capital | 100 USD | cumplido |
| Sin fills sintéticos | `paper_touch_fill_every_n=0`, sin `locked_spread` | cumplido |
| Fair value dimensionalmente correcto | log-moneyness | cumplido |

**Sesiones del batch hito (margin_max_v3):**  
`0` · `+2,50` · `+64,89` · `+28,44` · `0` · `-4,21` → total **+91,62 USD** paper en 6×3,5 min.

Config congelada del hito:  
`polymarket/config/maker_demo_100_usd_margin_best.json`  
Artefacto JSON: `polymarket/data_local/local_lab/margin_max_best.json`

---

## 2. Metodología (trazable)

### 2.1 Diagnóstico (por qué el “83%” inicial no valía)

1. **Fair value roto:** `(spot−strike)/(σ√T)` trataba σ como vol en dólares → fair colapsaba a 0,001 con ±1 USD.  
   **Fix:** `P_up = Φ(ln(S/K)/(σ√T))` en `src/pricing/fair_value.py` + test de no-colapso.
2. **Salidas sintéticas:** hazard / mean-reversion inventaban TP sin trade.  
   **Fix:** solo mid observable; hazard degradado a TP mid real.
3. **Inventario muteado al tope:** `apply_inventory_skew` devolvía `None` y no cotizaba salida.  
   **Fix:** con inventario siempre se cotiza el lado reductor.
4. **MTM inmediato post-fill:** infla WR mid-spread (útil como diagnóstico, no como evidencia de dinero).  
   **Decisión:** métrica de selección = inventario + TP/stop mid, sin flatten_after_fill.

### 2.2 Escalera de evidencia (ejecutada)

| Fase lab | WR | Avg net | Notas |
|----------|-----|---------|--------|
| Trial inflado (pre-fix) | 83% | +1,09 | **inválido** |
| Honest inventory (fair OK) | 40% | +0,28 | techo realista duro |
| Inventory + exit fix | 83% | +0,67 | céntimos |
| Income boost (size↑) | 83% | +8,88 | sizing×edge |
| Margin max v3 (hito) | **75%** | **+15,27** | stop $ cap + tiers |

### 2.3 Controles anti-autoengaño

- `paper_touch_fill_every_n = 0`
- `paper_pnl_mode ≠ locked_spread`
- `exit_hazard_per_s = 0` (sin fills inventados)
- `reject_adverse_fills = true`
- `max_loss_usdc` limita pérdida por posición
- Verdict de sesión: `LOCAL_PAPER_ONLY` / `verdict_binding: false`

### 2.4 Mecanismos de margen (investigación de fills)

- Sesiones top: margen sobre notional ~18–20%.
- Pérdidas tipicas: overtrading / inventario adverso.
- Respuesta: tiers soft/hard edge, `min_expected_pnl_usdc`, cooldown, `max_entry_fills`, TP por fracción de edge.

---

## 3. Qué es y qué no es este hito

| Sí | No |
|----|----|
| Evidencia de que el mecanismo *puede* generar PnL paper con feeds live Binance+CLOB | Dinero real en Polymarket |
| Base documentada para Fase A / paper 14d / screen | Screen vinculante #16 |
| Config reproducible | Garantía de WR≥75% out-of-sample indefinido |

**Live on-chain** sigue **prohibido** por `PREREG_16` hasta: Fase A ≥30d WS → paper maker ≥14d → screen PASA.  
Además no hay claves CLOB/wallet en el entorno actual.

---

## 4. Siguiente paso (este documento lo abre)

1. **Calibración escalonada (en curso):** mini-tests (~2.5 min) → adaptar riesgo → promover a ≥10–12 min si WR/avg pasan umbral.  
   Config base riesgo: `config/maker_demo_100_usd_risk_pack.json`  
   Script: `research/local_lab/calibrate_wr_ladder.py`  
   Controles nuevos: `session_kill_net_usdc`, anti-racha (`loss_size_penalty`), `fair_fade_exit`, size↓ / `max_loss_usdc`↓.
2. **Grabación local WS** (`data_local/local_lab/` o `phase_a_16` en Hetzner) — panel para replay.  
3. **Fase A oficial** en Hetzner+PM2 (`docs/PHASE_A_DEPLOY.md`).  
4. Solo después: paper firmado 14d → screen `sim_maker_quote` → micro-live.

Scripts de esta línea:

| Script | Rol |
|--------|-----|
| `research/local_lab/margin_max_loop.py` | Optimización margen $100 |
| `research/local_lab/calibrate_wr_ladder.py` | Mini-calibración → promoción ≥10 min |
| `research/local_lab/real_sim_confirm_loop.py` | Confirmación OOS + target↑ |
| `research/local_lab/analyze_income_margins.py` | Márgenes por fill |
| `research/local_lab/report_margin_best.py` | Resumen best |

---

## 5. Parámetros clave del hito (resumen)

- `min_edge=0.03`, `soft_edge=0.045`, `hard_edge=0.075`
- `quote_size_shares=42`, `max_size_mult=3.0`
- `min_take_profit=0.02` … `max_take_profit=0.09`, `tp_capture_frac=0.55`
- `stop_loss_mid=0.018`, `max_loss_usdc=6.0`
- `max_notional_per_side_usdc=48`, `max_inventory_usdc=55`

---

## 6. Firma del hito

- **Veredicto lab:** GO CONDICIONAL a Fase A / simulación OOS — **no** GO a live.  
- **Binding:** false  
- **Owner path:** continuar línea maker_edge + datos reales; no reabrir forecast #17.
