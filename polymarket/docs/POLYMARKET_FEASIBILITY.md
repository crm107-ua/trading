# Fase 0 — Viabilidad Polymarket Lab

**Fecha:** 2026-07-13  
**Probe artefacto:** `polymarket/data_local/phase0_probe.json`  
**Veredicto:** **GO condicionado** — APIs operativas; research con mid+slippage conservador; GO-live requiere depth propio.

---

## Checklist

| # | Pregunta | Resultado | Muerte |
|---|----------|-----------|--------|
| 0.1 | Acceso operativo (cuenta, wallet, geo, KYC) | **CONFIRMADO** por stakeholder — puede paper-trade | NO-GO si bloqueo legal |
| 0.2 | APIs funcionales | **PASS** — Gamma search, CLOB book, prices-history, WS market | NO-GO si auth bloquea research |
| 0.3 | Histórico backtest | **PASS parcial** — mid-only (`prices-history`); sin depth histórico gratuito | NO-GO solo si única vía es dataset de pago sin presupuesto |
| 0.4 | Latencia retail | **PASS condicional** — CLOB REST p50 ~50 ms; Binance p50 ~236 ms; WS first msg ~2,6 s | NO-GO si p95 > ventana edge (~segundos) en producción |
| 0.5 | Fees + resolución | **PASS documental** — taker ~2%; maker 0%; strike = apertura ventana BTC (oracle Polymarket) | Errores resolución = muerte operativa |
| 0.6 | Competencia bots $50k/mes | **INCONCLUSO en Fase 0** — requiere screen con fricción honesta | Muerte esperada clase A o C en screen |

---

## Evidencia probe (2026-07-13)

| Check | Valor |
|-------|-------|
| Gamma `public-search` activos BTC Up/Down | 5 eventos |
| CLOB `/book` | 200 OK (mercado muestra: solo asks, near resolution) |
| `prices-history` | 16–1440 puntos según ventana; **mid-only** |
| Binance RTT p50 | ~236 ms |
| CLOB book RTT p50 | ~50 ms |
| CLOB WS | 1 book update en 5 s (mercado poco líquido al cierre) |

---

## Hallazgos vinculantes

1. **Discovery:** usar `GET /public-search?q=Bitcoin+Up+or+Down&events_status=active`, no solo `/markets?tag=crypto`.
2. **Sin depth histórico:** backtest serio = grabar WS (`clob_recorder`) o slippage conservador en mid-only (riesgo falso PASA).
3. **Latencia retail:** REST CLOB rápido (~50 ms); feed Binance ~4× más lento — el cuello de botella es spot externo, no CLOB local.
4. **Mercados efímeros:** ventanas 5m rotan; discovery debe ejecutarse cada ciclo.

---

## Decisión GO/NO-GO

| Ámbito | Veredicto |
|--------|-----------|
| **Research + pre-reg #15** | **GO** |
| **Screen con mid-only** | **GO** con slippage escalonado + safety_buffer fijos en pre-reg |
| **Paper bot** | Solo tras screen PASS |
| **GO-live** | **NO-GO** hasta ≥30 días depth propio + paper OOS Sharpe ≥ 0,5 |

---

## Próximos pasos (orden fijo)

1. ~~Ideación adversarial~~ ✓
2. ~~Pre-registro congelado~~ ✓
3. ~~Collectors + simulador~~ ✓ (infra)
4. ~~Screen~~ → **SCREEN_INVÁLIDO** (2026-07-13) — ver `SCREEN_15_INVALIDATION.md`
5. ~~Fila #15 registry~~ ✓ — `NO_EVALUABLE`; rama en **PAUSA**

**No proceder** a grabación 30 días salvo reapertura explícita con nuevo mecanismo (#16+).

---

*Fase 0 no valida edge; solo viabilidad técnica. #15 cerrado sin juzgar hipótesis.*
