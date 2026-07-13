# Laboratorio local — Polymarket

**Sin prod.** Sin on-chain. Sin proyecciones anuales. Sin registry hasta pre-reg + screen.

---

## Frontera (congelada)

Este lab **solo puede emitir veredictos negativos**.

- **Puede matar una idea**: `0 fills en 1h`, `adverse_rate > 55%`, fallos de latencia/stale, etc.
- **No puede “aprobar”**: un fill virtual **no** implica fill real (no hay cola / prioridad en el book).  
  Si el simulador marca fill cuando un trade cruza tu precio, te estás atribuyendo fills que en real se llevarían quienes estaban antes.

**Regla:** cualquier métrica “verde” del lab es *no-evidencia*; solo sirve para detectar bugs o para descartar ideas.

---

## Qué es

Entorno para **probar estrategias en vivo** contra datos reales (Binance + CLOB) con cartera virtual.

| Ruta | Uso |
|------|-----|
| `data_local/local_lab/` | Grabación opcional (mismo formato fase A) |
| `data_local/local_lab/<strategy>/session_*/` | Paper: fills + `report.json` de sesión |

**No sustituye** fase A Hetzner ni screen fase C. Es I+D local.

---

## Comandos

```powershell
cd C:\Users\carom\Desktop\trading
$env:PYTHONUTF8 = "1"

# Paper maker #16 — 30 min
python -m polymarket.research.local_lab.run_local_lab --paper --strategy maker_16 --minutes 30

# Grabar + paper en paralelo — 1 h
python -m polymarket.research.local_lab.run_local_lab --record --paper --minutes 60

# Probar hipótesis local (sin pre-reg aún)
python -m polymarket.research.local_lab.run_local_lab --paper --strategy wide_spread_probe --minutes 45
```

También: `python -m polymarket.src.bot --mode paper-maker --minutes 30`

---

## Estrategias disponibles (local)

| ID | Origen | Descripción |
|----|--------|-------------|
| `maker_16` | Pre-reg #16 congelado | Bid/ask fair ± spread; params `maker.json` |
| `wide_spread_probe` | Idea #17-local | Solo cotiza si spread mercado ≥ 5¢ |
| `tight_mid_fade` | Idea #18-local | Solo cuando spot>strike y mid < fair − 3¢ |

Nuevas ideas: añadir en `strategies.py` + probar aquí. **Registry (#17, #18…)** solo tras pre-reg escrito.

---

## Control de comparaciones múltiples (congelado)

Para evitar “shopping” de estrategias:

- **Máximo 1 idea activa a la vez** (además de `maker_16`, que es infraestructura).
- **Máximo 3 sesiones por idea** (p. ej. 3×60 min). Si no mata la idea, **no** asciende por “sesión verde”.
- Una idea solo asciende a pre-reg por **mecanismo argumentado** (2 frases) + chequeos de muerte (adverse/latencia), **nunca** por PnL local.
- Todo el tiempo del lab consume el presupuesto de **≤6 h/semana** de #16.

---

## Ideas para probar después (papel)

1. **Complemento Up+Down** — suma bid_up + ask_down < 1 − fees (familia 1; riesgo pierna incompleta).
2. **Quote solo últimos 90s** — menos inventario, más adverse en cierre de ventana.
3. **Solo ask en tendencia** — vender Up caro cuando spot sube fuerte (probe `tight_mid_fade`).

Muerte en papel si adverse > 55% o spread < 2× adverse en sesiones acumuladas.

---

## Qué mirar en `report.json` de sesión

- `fills`, `adverse_rate`, `net_session_usdc` — **solo esa sesión**
- Si `adverse_rate` > 0.55 → estrategia mala para retail lento
- Si `fills` = 0 en 30 min → sin liquidez que cruce tus quotes; no es fallo del código

**Prohibido:**
- Extrapolar `net_session_usdc` a mes/año.
- Usar el lab como comparativa de “la mejor estrategia”.
- Rehabilitar `sim_ganancias_eur`: está en **cuarentena** y se niega a correr sin PASA fase C.

---

## Relación con protocolo #16

| Fase oficial | Lab local |
|--------------|-----------|
| Fase A 30d Hetzner | `--record` opcional en PC (smoke / local_lab) |
| Fase B paper 14d | `--paper` acumulando sesiones locales |
| Fase C screen | `sim_maker_quote` + replay 30d — **único PnL vinculante** |

El lab local acelera **aprender** (¿hay fills? ¿adverse?) sin saltarse el screen.
