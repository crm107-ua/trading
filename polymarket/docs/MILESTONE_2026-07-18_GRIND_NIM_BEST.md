# Hito 2026-07-18 — Grind NIM BEST (WR ≥ 75% micro 5/10/15€)

**Estado:** CAMPEÓN DE LABORATORIO (paper) · **no** es PnL on-chain  
**Metodología:** `grind_nim_flow` → snapshot `grind_nim_best`  
**Stack IA:** NVIDIA NIM hybrid + profit-assist + grind (`nemotron-mini-4b-instruct`)  
**Capital de referencia:** 10 EUR (validación corta también en 5 / 15)  
**Fecha:** 2026-07-18  

---

## 1. Objetivo

| Criterio | Umbral | Resultado campeón |
|----------|--------|-------------------|
| WR en sesiones **con fills** | ≥ 75% | **80%** (4W / 1L) |
| Sesiones traded | ≥ 3 | **5** |
| Total paper @10€ | > 0 | **+0.37 EUR** |
| Sin fills sintéticos | `paper_touch_fill_every_n=0` | cumplido |
| 1 entrada / sesión | `max_entry_fills=1` | cumplido |

**Batch campeón:** 6 sesiones × 5.0 min, capital 10 EUR, floors live-exact con `preserve_selectivity`.

| Sesión | Fills | Side | Net (EUR) |
|--------|-------|------|-----------|
| 1 | 0 | — | 0.00 |
| 2 | 1 | bid | **+0.43** |
| 3 | 1 | bid | **+0.07** |
| 4 | 1 | bid | **+0.18** |
| 5 | 1 | bid | **+0.12** |
| 6 | 1 | bid | **−0.43** |

Artefacto de iteración: `data_local/local_lab/grind_iterate/iterate_20260718_145637.json`  
Config congelada: `polymarket/config/maker_demo_grind_nim_best.json`  
Catálogo panel: id **`grind_nim_best`**

---

## 2. Método ganador (cómo opera)

### 2.1 Idea

Acumular **wins pequeños** en BTC Up/Down 5m con size micro (5 shares), **solo lado cheap (bid Up)**, salidas tempranas (lock / cut) y NVIDIA como filtro hybrid + asistente de flatten. Prioridad: **WR alto**, no maximizar un trade.

### 2.2 Entrada

1. Estrategia `maker_edge` con banda mid **0.28–0.72** (evita colas 0.05 / 0.95).
2. `min_edge ≈ 0.026`, `min_z ≈ 0.85`, ventana tiempo **25–480 s** (sin starve por ventana estrecha).
3. **`max_abs_edge = 0.09`**: si |fair − mid| es enorme, el modelo miente (p.ej. fair 0.5 vs mid 0.95) → **no cotizar**.
4. **`cheap_side_only = true`**: solo bid Up. Prohibido ask/rich (los fades rich destruyeron WR en trials previos).
5. NVIDIA hybrid: en modo grind **no** auto-quote por `rule_strong_edge` (deja decidir a NIM en zona ambigua).
6. Una sola entrada (`max_entry_fills=1`, no pyramid).

### 2.3 Salida (grind + NIM)

| Regla | Valor campeón |
|-------|----------------|
| Lock profit | **0.10 EUR** |
| Max loss | **0.10 EUR** (+ corte duro por PnL no realizado en paper) |
| Stop mid | 0.008 |
| Flatten antes de fin de ventana | ≥ 90 s |
| NIM grind | `NVIDIA_NIM_GRIND=1`, bank verde ≥ ~0.06–0.08, cut rojo temprano |
| Profit assist | `NVIDIA_NIM_PROFIT_ASSIST=1`, exit poll ~5 s |

### 2.4 Size / capital

- `quote_size_shares = 5` (mínimo CLOB).
- Caps notional/inventario acotados al capital de sesión.
- Pensado para apuestas **5 / 10 / 15 EUR**, no para book de 100€.

### 2.5 Variables de entorno (corrida campeona)

```text
NVIDIA_NIM_MODE=hybrid
NVIDIA_NIM_PROFIT_ASSIST=1
NVIDIA_NIM_GRIND=1
NVIDIA_NIM_STRONG_EDGE_MULT=2.8
NVIDIA_NIM_EXIT_EVERY_S=5
NVIDIA_NIM_MODEL=nvidia/nemotron-mini-4b-instruct
```

Iterador: `python -m polymarket.research.local_lab.iterate_grind_wr`

---

## 3. Por qué este método ganó (y qué falló antes)

1. **Starve:** mid/time demasiado estrechos → 0 fills → WR indefinido.  
   Fix: `grind_nim_flow` + ventana 25–480 s.
2. **Floors live anulaban grind:** `apply_live_clob_floors` subía `max_loss` ≥ 0.30 y `lock` ≥ 0.15.  
   Fix: si `preserve_selectivity` / label grind → suelos bajos (0.06–0.25).
3. **Rich-side tóxico:** asks con “edge” falso vs fair → pérdidas −0.5€.  
   Fix: `cheap_side_only` + `max_abs_edge`.
4. **Auto-quote strong edge** saltaba NIM.  
   Fix: en grind mode no hay `rule_strong_edge` automático.

Baseline misma ronda: `hito_margin` @10€ → WR **33%**, total −0.13 (peor que grind flow).

---

## 4. Validación OOS corta (5€ / 15€)

Muestra **más corta** (4×4 min), misma familia de cfg:

| Capital | WR traded | Total | Nota |
|---------|-----------|-------|------|
| 10 EUR (campeón) | **80%** | **+0.37** | 6×5 min |
| 5 EUR | 33% | −0.27 | 4×4 min, régimen distinto |
| 15 EUR | 0% | −0.64 | 4×4 min, 2 fills |

**Conclusión:** el 80% es hito de lab @10€ con muestra adecuada; **no** está demostrado estable en 5/15 con pocas sesiones. Revalidar 6×5 (o más) antes de live.

---

## 5. Cómo reproducir / usar en panel

```powershell
cd C:\Users\carom\Desktop\trading
$env:PYTHONUNBUFFERED='1'
python -m polymarket.research.local_lab.iterate_grind_wr `
  --rounds 1 --sessions 6 --minutes 5 `
  --strategies grind_nim_flow --capitals 10
```

Panel web lab: estrategia **`grind_nim_best`** (badge CHAMP).

---

## 6. Límites (leer antes de dinero real)

- Paper mid-mark, **no** fills CLOB reales.
- Una pérdida del batch campeón fue **−0.43** (por encima del techo teórico 0.10) → el “siempre gana poco” **aún no** está cerrado.
- Live requiere checklist dry + balance ≥ ~5 pUSD; con ~0.83 pUSD el live real sigue bloqueado.
- WR paper ≠ expectativa on-chain.

---

## 7. Archivos clave

| Archivo | Rol |
|---------|-----|
| `config/maker_demo_grind_nim_best.json` | Config congelada campeona |
| `config/maker_demo_grind_nim_flow.json` | Base tradeable del método |
| `research/local_lab/iterate_grind_wr.py` | Iterador WR / grind + NIM |
| `web_lab/catalog.py` | Entrada `grind_nim_best` |
| `src/ai/decision_engine.py` | Reglas grind / hybrid |
| `docs/NVIDIA_NIM.md` | Contexto NIM |

---

## 8. Veredicto

**Método ganador de lab:** Grind NIM (`cheap_side_only` + `max_abs_edge` + lock/loss 0.10 + NVIDIA hybrid/grind)  
**Evidencia binding de lab:** WR **80%** @10 EUR, +0.37 EUR paper, 5 sesiones traded.  
**Siguiente paso:** revalidar 5/10/15 con batches largos; solo entonces dry-E2E → live micro con capital ≥ 5 pUSD.
