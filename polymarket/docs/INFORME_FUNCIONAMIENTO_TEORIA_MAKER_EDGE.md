# Informe — Funcionamiento y teoría (maker_edge, paper real-feed)

**Fecha:** 2026-07-16 16:57 UTC  
**Ámbito:** Polymarket BTC Up/Down 5m · capital lab 100 USD · **no** on-chain  
**Binding:** false (lab / simulación; no screen PREREG_16)

---

## 1. Teoría del mecanismo

### 1.1 Edge de maker selectivo

El bot no “predice” el evento con LLM. Cotiza como **maker** solo cuando el fair value
binomial (log-moneyness + σ) se separa del mid del CLOB por encima de `min_edge`:

- Mercado **barato** vs fair → bid al touch (comprar Up).
- Mercado **rico** vs fair → ask al touch (vender Up / short).
- Size escala con soft/hard edge (más edge → más size, acotado).

El PnL paper viene de **fills reales del book** (Binance spot + CLOB WS) y salidas a mid
(TP/stop / fair-fade / flatten de ventana). Sin `paper_touch_fill` ni hazard sintético.

### 1.2 Por qué WR y avg pelean

| Palanca | Efecto en WR | Efecto en avg |
|---------|--------------|---------------|
| Subir `min_edge` / bajar entries | ↑ (menos trades tóxicos) | ↓ o flat (menos oportunidad) |
| Subir `quote_size` / `max_size_mult` | ↓ (cola de pérdidas) | ↑ en wins, ↓↓ en losses |
| `max_loss_usdc` + kill sesión | ↑ (corta cola) | tope el downside |
| Anti-racha (size×0.5, pausa) | ↑ estabilidad | reduce recuperación agresiva |

Evidencia dura del día: OOS trial 1 (size~42) WR **50%** avg **+$15.7**; trial 2 (size↑)
WR **37.5%** avg **−$7.5**. El hito lab margin_max_v3 logró WR **75%** avg **+$15.3**
en 6×3.5 min — reproducible como referencia, no como garantía OOS.

### 1.3 Hipótesis de trabajo

1. El edge existe en ventanas cortas cuando fair≠mid y el book no es tóxico.
2. La **cola izquierda** (losses −20…−40) destruye WR al subir size.
3. Confirmar WR≥75% OOS exige selectividad + caps, aceptando avg más bajo que el hito.
4. Sesiones de 1.5–2 min con edge alto pueden dar **0 fills** → no miden WR (ruido).

---

## 2. Funcionamiento del sistema (pipeline)

```
Binance spot WS ──┐
                  ├─→ fair_value(Φ(ln S/K)/(σ√T))
CLOB book/trades ─┘         │
                            ▼
                     maker_edge filter
                            │
                     paper fills + inventory
                            │
              TP/stop/fair-fade/session-kill
                            │
                     report.json / batch WR
```

- **Daemons:** `daemon_btc_feed` + `daemon_clob_recorder` → `data_local/local_lab/`.
- **Estrategia:** `research/local_lab/strategies.py` → `maker_edge`.
- **Motor paper:** `paper_maker.py` (riesgo: kill, anti-racha, fair_fade).
- **Loops:** calibrate / confirm_wr_fast / multi_real_probe (lab only).

---

## 3. Resultados agregados (sesiones con report)

### Hito margen (referencia) (`margin_max_v3`)

- Sesiones: **6** · con fills: **4**
- WR (traded): **75.0%** (3W / 1L)
- Avg net traded: **22.905** · Total: **91.62**
- Mejor / peor: **64.89** / **-4.21**

### OOS real-sim trial 1 (`real_sim_oos_v1`)

> El disco mezcla el batch limpio con reinicios del watchdog. **Verdad OOS:**

- **Batch limpio 8×5 min (`v2_140332_*`):** WR **50%** · avg **+$15.73** · total **+$125.81** · 4 losses  
- Agregado bruto disco (~36% WR) → **descartar** (contaminado por restarts)

### OOS real-sim trial 2 (size↑) — batch limpio

- **8×5 min trial 2:** WR **37.5%** · avg **−$7.47** · total **−$59.80** (colas −43 / −34)  
- El agregado disco que mezcla trial 2+3 parciales **no** sustituye esta fila

### Risk pack (cola↓) (`risk_pack_v1`)

- Sesiones: **6** · con fills: **6**
- WR (traded): **33.3%** (2W / 4L)
- Avg net traded: **-0.1217** · Total: **-0.73**
- Mejor / peor: **4.65** / **-3.73**

### Calibración mini best (`cal_g1_161519`)

- Sesiones: **5** · con fills: **3**
- WR (traded): **66.7%** (2W / 1L)
- Avg net traded: **3.0367** · Total: **9.11**
- Mejor / peor: **9.11** / **-4.5**

### Probe selectivo (`probe_selective`)

- Sesiones: **3** · con fills: **0**
- WR (traded): **n/a** (0W / 0L)
- Avg net traded: **None** · Total: **0.0**
- Mejor / peor: **None** / **None**

### Probe balance (`probe_balance`)

- Sesiones: **3** · con fills: **3**
- WR (traded): **0.0%** (0W / 3L)
- Avg net traded: **-3.4233** · Total: **-10.27**
- Mejor / peor: **-1.3** / **-7.67**

### Probe margen ref (`probe_margin_ref`)

- Sesiones: **3** · con fills: **1**
- WR (traded): **0.0%** (0W / 1L)
- Avg net traded: **-2.94** · Total: **-2.94**
- Mejor / peor: **-2.94** / **-2.94**

### Probe multi-config (corrida dedicada 3×2 min, ~18:33–16:57 UTC)

| Variante | Size | Edge | Resultado | Lectura |
|----------|------|------|-----------|---------|
| selective | 22 | 0.04 | 0 fills / 3 sess | Filtro demasiado alto para ventanas de 2 min → **no mide WR** |
| balance | 26 | 0.032 | 0W/3L · total −10.27 | Régimen adverso corto; stop/kill no bastan |
| margin_ref | 32 | 0.03 | 0W/1L · −2.94 (2 flat) | Hito no se reproduce en 2 min |

**Implicación teórica:** WR≥75% necesita **horizonte ≥3.5–5 min** (o más) y mercado con edge; minis de 2 min sirven para calibrar riesgo, no para certificar WR.

### Calibración mini (historial)

- Round 1 `risk_pack_v1`: WR=0.3333 avg=0.4 losses=2 fail=loss_tail
- Round 2 `cal_g1_161519`: WR=0.6667 avg=3.0367 losses=1 fail=wr

---

## 4. Veredicto de funcionamiento

| Pregunta | Respuesta |
|----------|-----------|
| ¿El mecanismo genera PnL paper con feeds reales? | **Sí** (hito + OOS trial 1 positivo en total) |
| ¿WR≥75% estable OOS? | **Aún no confirmado** fuera del batch hito; OOS 50% / calibración ~67% best |
| ¿Subir size sube ingresos seguros? | **No** — rompe WR vía cola |
| ¿Listo para live? | **No** — PREREG_16 + sin claves CLOB |

## 5. Siguiente paso recomendado

1. Congelar config con WR≥75% en batch ≥4×10 min (promote).
2. Mantener size≤30 y `max_loss_usdc`≤3.5 hasta cola acotada.
3. No relanzar `autonomous_oos_driver` / watchdogs que reinician Trial 1.
4. Fase A WS ≥30d antes de paper firmado / screen.

_Artefacto JSON:_ `data_local/local_lab/informe_funcionamiento_latest.json`
