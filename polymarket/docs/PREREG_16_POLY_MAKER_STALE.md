# Pre-registro #16 — Polymarket Maker Stale-Quote (post-only)

**Congelado:** 2026-07-13 — **antes de grabación extendida, paper, screen o lectura de resultados.**  
**Fase 0:** `docs/POLYMARKET_FEASIBILITY.md` (GO condicionado — reutilizado).  
**#15:** `SCREEN_INVÁLIDO` — mecanismo **distinto** (taker FAK vs maker post-only); no es iteración de #15.

**Mecanismo (vinculante):** el bot **publica** quotes bid/ask en el CLOB ancladas a fair value desde spot BTC; cuando spot se mueve, cancela y repone antes de que el libro quede obsoleto. Gana el spread (maker 0%) de takers que cruzan; pierde si le fillan y spot sigue en contra (**adverse selection**). Quién pierde: el bot si actualiza lento; takers si el quote ya incorporaba el movimiento.

---

## Por qué no es isomorfismo con #15

| | #15 (cerrado) | #16 (este pre-reg) |
|---|---------------|---------------------|
| Rol | **Taker** — compra quotes ajenas obsoletas | **Maker** — publica quotes propias |
| Fee | 2% taker | **0%** maker |
| Edge | `fair - ask` menos fricción | **Spread capturado** menos adverse selection |
| Hipótesis económica | Explotar lag del CLOB | **No ser** el lag del CLOB |
| Veredicto previo | No evaluable | — |

Misma familia del artículo (2+3), **lado opuesto del trade**. Cuenta como intento nuevo.

---

## Decisiones congeladas

| Tema | Decisión |
|------|----------|
| **Familia** | Maker fair-value quoting (2+3) — **no** arb temporal multi-pata; **no** taker |
| **Universo** | `Bitcoin Up or Down` ventana **5m** activos (Gamma `public-search`) |
| **Token** | Solo token **Up** por ventana (una pata; Down = complemento implícito) |
| **Motor** | Nuevo `research/poly_lab/sim_maker_quote.py` + paper `src/bot.py --mode paper-maker` |
| **Capital referencia** | **10 000 USDC** |
| **Presupuesto** | **≤ 6 h/semana**, cierre **2026-09-30** |
| **Runs** | **Un solo** screen tras paper; sin hyperopt de umbrales |

---

## Datos (orden obligatorio — sin saltar fases)

| Fase | Duración | Entregable | GO siguiente fase |
|------|----------|------------|-------------------|
| **A — Grabación** | **≥30 días** wall-clock | `data_local/phase_a_16/` — ver abajo | Uptime conjunto **≥95%**; si no → **repetir A** |
| **B — Paper maker** | **≥14 días** | `data_local/paper_maker_16/` logs sin firma on-chain | Ningún P-* dispara |
| **C — Screen único** | 1 run | `research/output/poly_16/<run_id>/report.json` | Veredicto vinculante |

**Prohibido:** screen antes de fase A; live antes de screen PASA; synthetic para veredicto.

### Fase A — spec congelada (`config/phase_a.json`)

| Parámetro | Valor |
|-----------|-------|
| **Scope** | Solo **BTC Up/Down 5m** — **15m excluido** |
| **Host** | Hetzner Linux + PM2 — **no** Windows desktop |
| **Procesos** | Long-running con reconexión WS + backoff — **no** cron `--duration` |
| **Reloj** | `time.time_ns()` mismo host; NTP activo; `ts_ns` + `recv_ts_ns` por evento |
| **Book depth** | **Top 10 niveles** bid/ask — congelado |
| **Formato** | JSONL horario UTC, gzip |
| **Gaps** | `[start_ns, end_ns]` en manifest — replay **excluye** gaps WS, no interpola |
| **Rotación mercado** | Discovery slug `btc-updown-5m-{ts}` + poll 10s cerca del rollover; pre-suscribe **45s** antes del cierre (ver corrección abajo) |
| **Manifest** | `manifest.json` actualizado cada hora + health-check diario |
| **Uptime mínimo** | **≥95%** sobre tiempo con ventana 5m activa — **no** penaliza huecos Gamma entre ventanas |
| **Fallo A** | Uptime <95% o <30d → **repetir fase A entera** — no aprovechar panel parcial |

Deploy: [`docs/PHASE_A_DEPLOY.md`](PHASE_A_DEPLOY.md)

---

## Corrección proceso 2026-07-13 (pre-suscripción + huecos Gamma)

| Tema | Decisión documentada |
|------|---------------------|
| **Pre-suscripción** | Umbral congelado **45s** (antes 60s en borrador). Smoke 2026-07-13: primer log ~38–45s antes del rollover; poll 10s cerca del cierre. Book activo desde apertura de ventana — suficiente. |
| **Huecos Gamma** | Entre ventanas 5m `public-search` puede no listar mercado activo (minutos sin fila). **No** es gap del recorder. Manifest: `market_inactive_periods[]` ≠ `feeds.*.gaps[]`. `validate_phase_a` no penaliza tiempo sin ventana. |
| **Discovery** | Slug `btc-updown-5m-{unix_start}` evita depender del índice Gamma tardío. |

---

## Feed (congelado)

| Fuente | Modo | Muerte si |
|--------|------|-----------|
| BTC spot | **WebSocket** `btcusdt@trade` (Binance) | Solo REST poll |
| CLOB | **WebSocket** `market` channel | Solo REST `/book` en loop |
| Strike / end | Gamma API por ventana | Strike inventado |

`kill_switch_feed_stale_ms`: **2000** (más estricto que #15).

---

## Pricing (parámetros fijos — prohibido optimizar)

Fair value (igual que #15):

```
P_up = Φ( (spot - strike) / (σ × √(time_remaining_years)) )
```

Quotes post-only:

```
half_spread = 0.015          # 1.5¢ cada lado — fijo
bid_up  = clip(P_up - half_spread - safety_buffer, 0.01, 0.98)
ask_up  = clip(P_up + half_spread + safety_buffer, 0.02, 0.99)
```

| Parámetro | Valor |
|-----------|-------|
| `sigma_annual` | **0.55** |
| `half_spread` | **0.015** |
| `safety_buffer` | **0.005** |
| `maker_fee` | **0.00** |
| `quote_size_shares` | **100** |
| `requote_spot_move_usd` | **25** — cancel/replace si \|Δspot\| ≥ 25 USD desde último quote |
| `max_open_orders_per_market` | **2** (bid + ask) |

---

## Ejecución

| Modo | Elección |
|------|----------|
| Tipo orden | **GTC post-only** únicamente |
| Taker / FAK | **Prohibido** en #16 |
| Tamaño máx notional | **400 USDC** por lado por ventana |
| Inventario máx | **±300 USDC** neto Up por ventana |
| Fin ventana | Cancel all + flatten a mercado **solo paper**; live flatten manual flag |

---

## PnL (simulador y paper)

Descomposición obligatoria en reporte:

| Componente | Definición |
|------------|------------|
| `spread_captured` | Precio fill vs mid fair al momento del fill, lado maker |
| `adverse_selection_cost` | PnL mark-to-market a **+500 ms** del fill si spot se movió en contra |
| `inventory_pnl` | Hasta resolución (0/1) |
| `friction` | Slippage en flatten simulado + gas Polygon negligible |
| `account_return` | Sobre bankroll 10k USDC |

**Adverse selection (definición operativa):** fill en bid y spot bajó ≥10 USD en 500 ms, o fill en ask y spot subió ≥10 USD.

---

## Condiciones de muerte (pre-escritas)

### Paper (fase B) — cualquiera → no screen

| ID | Condición | Umbral |
|----|-----------|--------|
| **P-1** | Tasa adverse selection | > **55%** de fills |
| **P-2** | Spread capturado acumulado < 2× coste adverse selection acumulado | igual #14/#15 |
| **P-3** | p95 latencia spot-move → cancel/replace | > **1000 ms** |
| **P-4** | Días con inventario \|net\| > límite | > **30%** de días paper |

### Screen (fase C) — un run

| ID | Condición | Umbral |
|----|-----------|--------|
| **D-1** | Igual P-2 en replay | spread < 2× adverse |
| **D-2** | Igual P-1 en replay | adverse > 55% |
| **D-3** | PnL neto OOS (mitad temporal 2) | ≤ **0** |
| **D-4** | Sharpe OOS | < **0.5** |
| **D-5** | Concentración PnL una ventana | > **40%** |

Cualquier P-* en paper o D-* en screen → **MUERTA** sin apelación.  
Si faltan datos fase A → **SCREEN_INVÁLIDO** (no MUERTA de mercado).

---

## Validación (un run)

| Bloque | Detalle |
|--------|---------|
| Split | IS / OOS por mitad de ventanas 5m en panel grabado |
| Replay | Depth WS propio; **prohibido** synthetic para veredicto |
| Artefacto | `research/output/poly_16/<run_id>/report.json` |
| Veredicto | **PASA** solo si ningún D dispara **y** PnL neto OOS > 0 **y** P-1..P-4 pasaron en paper |

---

## Techo económico (10k USDC)

| Supuesto | Orden magnitud |
|----------|----------------|
| Fills maker/día | 10–40 |
| Spread neto/fill | 0,5–1,5¢ × size |
| Adverse selection | Puede comerse el spread si latencia perdedora |
| Neto anual optimista | **300–1 200 USDC/año** si P-1 < 50% |
| Coste fase A | ~30 días máquina + disco; **sunk cost** antes de saber |

El presupuesto 6 h/semana cubre **implementación + paper**, no garantiza edge.

---

## Checklist reapertura (cumplimiento)

| Criterio `PROJECT_STATUS.md` | #16 |
|------------------------------|-----|
| Mecanismo nuevo (2 frases) | ✓ maker vs taker #15 |
| Pre-reg congelado antes de datos | ✓ este documento |
| Presupuesto + fecha cierre | ✓ 6 h/sem, 2026-09-30 |
| Un solo run screen | ✓ |

---

*Congelado. Prohibido ajustar half_spread, requote_spot_move_usd, σ o umbrales P/D tras ver PnL.*
