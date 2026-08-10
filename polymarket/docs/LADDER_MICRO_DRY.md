# Temperature Ladder — micro dry-run live

**Estrategia:** champion v3  
**Config:** `polymarket/config/weather_ladder_micro_dry.json`  
**Cap:** $25 · **DRY_RUN obligatorio** · restaura `POLY_LIVE_ARMED=0`

## Qué montamos

| Pieza | Rol |
|-------|-----|
| `weather_ladder_live.py` | Harness `book_sim` + `clob_dry` + `watch` |
| `ladder_go_live_check.py` | Gate `LADDER_DRY_READY` (separado del maker) |
| `ClobLiveClient.connect(derive_api_creds=True)` | Deriva L2 keys desde `POLY_PRIVATE_KEY` |
| Floors live | min 5 shares / ≥$1 notional / abort basket parcial |
| `max_per_city` + `horizon_first` | Evita quemar bankroll en una ciudad |
| Smoke dry | Si no hay edge champion, 1 `would_post` de plomería |

## Comandos

```bash
python3 -m polymarket.research.local_lab.ladder_go_live_check
python3 -m polymarket.research.local_lab.weather_ladder_live --mode both
python3 -m polymarket.research.local_lab.weather_ladder_live --mode watch --watch-rounds 10 --watch-interval 180
python3 -m polymarket.research.local_lab.winning_desk --maker-rounds 0 --micro-dry
```

## Resultado sesión `20260810_043053`

- Check: **LADDER_DRY_READY**
- Balance wallet: **$3.45**
- Open markets: 8 · takes champion: **0** (libros caros; filtro correcto)
- Near-miss: Shanghai 2026-08-12 basket **0.66** / EV **+0.29** (vigilancia, no take)
- CLOB dry smoke: `DRY_RUN` BUY 16.67 @ 0.06 (HK 37°C) — **0 on-chain**
- Overall: **MICRO_DRY_PATH_READY**
- Tras sesión: `ARMED=0` `DRY_RUN=1`

## Lectura

El camino live está montado y probado. Hoy el mercado abierto **no** ofrece el basket barato del research; el sistema espera (watch) en lugar de forzar entradas.

Dinero real sigue bloqueado: este harness **nunca** pone `DRY_RUN=0`.
