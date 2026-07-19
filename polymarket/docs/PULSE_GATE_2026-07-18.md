# PulseGate — método pionero (2026-07-18)

**Estado:** implementación + caza paper · **no** es PnL on-chain  
**Live:** `POLY_LIVE_ARMED=0` · `POLY_LIVE_DRY_RUN=1`

## Por qué el DNA anterior fallaba

1. **Adverse selection:** `|fair−mid|` con σ fija invita a fadraar un mid ya informado.
2. **Strike paper sesgado:** al unirse mid-ventana, `strike≈spot_join` ≠ open real.
3. **Settlement manip (lit. 2026):** en BTC 5m, el flujo tóxico se concentra en los últimos segundos y en odds cercanos a 50/50 (Stanford/SMU, arXiv:2606.31675).
4. **Sin filtro de régimen/toxicidad:** operar colas o libros ask-heavy destruye WR.

## Tesis PulseGate

No predecir dirección a ciegas. Capturar **latencia BTC spot → libro Polymarket** solo cuando:

| Gate | Rol |
|------|-----|
| Strike fresco | Solo si `join_age ≤ max_window_join_age_s` (~45s) |
| Régimen mid | Banda viva ~0.38–0.62 (fuera de lotería) |
| Blackout settlement | No entrar si `time_rem < 110s` (ni caos de apertura si `>260s`) |
| Momentum BTC | UP: `spot−strike≥lead` + vel+ · DOWN simétrico: lead− + vel− |
| Edge + z | `|fair−mid|` en banda; dirección alineada al momentum |
| Imbalance | Bid-heavy para bids / ask-heavy para asks (anti tóxico) |
| Persistencia | Señal estable N polls |
| Skip ventana | Si activa está en blackout o join tarde → saltar a la siguiente |

Estrategia: `maker_pulse` · config: `maker_demo_pulse_gate.json` · hunt: `pulse_gate_hunt.py`

## Comandos

```bash
pytest polymarket/tests/test_maker_pulse.py -q

SIM_NIM_MODEL=nvidia/nemotron-mini-4b-instruct \
python -m polymarket.research.local_lab.pulse_gate_hunt \
  --capitals 5,10 --sessions 4 --minutes 3 --parallel 4
```

## Criterio de promoción

WR traded ≥70% con ≥2 sesiones con fills en **5€ y 10€** → promover a `grind_nim_best` (paper).  
**No** armar live real hasta dry-E2E + checklist.

## Hallazgos cloud 2026-07-18 (noche UTC)

1. **Binance.US congelaba el last trade** → `lead=0` eterno. Fix: mediana Coinbase+OKX+Kraken.
2. Sellar strike al open **anulaba** el lead vs open; PulseGate usa **roll 8s**.
3. Saltar pronto a la siguiente ventana aparcaba el bot en mercados aún cerrados (`trusted=False`). Fix: solo blackout settlement.
4. En la ventana de caza, muchos books en **mid 0.85–0.97** (fuera de régimen) → starve correcto (no lotería).
5. Estado: método implementado + tests verdes; **aún sin WR≥70% medido** en fills reales de esta noche. Hunt sigue.
