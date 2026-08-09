# Copy / micro-spread sleeve vs Temperature Ladder

## La historia viral (“47 wallets que nunca pierden”, $300→$1429 dormido)

Esa narrativa **no se sostiene** como estrategia verificable:

- En leaderboards reales, con muestra ≥15 cierres, **casi nadie tiene 0 losses**.
- “Compra 0.48 / vende 0.52 cada pocos segundos” es **market-making / follow-mid** en ventanas cortas (BTC-5m u otros), no magia copy-paste.
- Curvas que “solo suben” suelen omitir fees, adverse selection, inventarios tóxicos y rachas.

## Qué implementamos (paper)

1. `elite_wallet_scan.py` — escanea leaderboard, puntúa candidatos (WR, PnL, estilo).
2. `maker_demo_copy_micro_spread.json` — sleeve `maker_follow` con bandas **0.52 / 0.48** y TP ~4¢.
3. `compare_copy_spread_vs_ladder.py` — carrera honest ladder vs micro-spread vs grind.

## Cómo usarlo

```bash
python -m polymarket.research.local_lab.elite_wallet_scan --limit 25 --period month
python -m polymarket.research.local_lab.compare_copy_spread_vs_ladder --spread-rounds 5 --minutes 3.5
python -m polymarket.research.local_lab.winning_desk --idle-sleeve micro_spread --maker-rounds 3
```

## Carrera paper (`compare_20260809_233154`)

| Sleeve | PnL | WR | Notas |
|--------|-----|----|-------|
| Temperature Ladder | **+$230.48** | 7/9 (77.8%) | scorecard resolved |
| Micro-spread (`maker_follow` 0.48/0.52) | +$0.40 | 4/4 fills | 5 rondas × 3.5 min |
| Grind NIM control | −$0.97 | 0/2 | idle BTC-5m |

Ranking: `ladder` ≫ `micro_spread` > `grind_nim`. Veredicto: **LADDER_STILL_BEST**.

Scan leaderboard: con `closed-positions` ordenado ASC+DESC por REALIZEDPNL, **casi 0 wallets “never lose” con n≥15** (la cifra viral “47” no se reproduce).

## Veredicto operativo (regla del desk)

- **Primario:** Temperature Ladder multi-sleeve (research WR100% / paper 12d +$418).
- **Secundario idle:** micro-spread **sí supera** grind en esta carrera (+0.40 vs −0.97), pero **no** es mejor que el ladder ni escala a “$1k dormido”.
- **No** armar live copy de wallets sin gate (`POLY_LIVE_ARMED=0`).
