# Wallet Take Reality Sim

Simulación profesional del bot Temperature Ladder con **tu saldo real** (p.ej. `$3.45`).

## Qué responde

1. ¿Cabe un take DNA ahora con floors CLOB (5 shares + ≥$1/pierna)?
2. ¿Qué pasa si gana / pierde / fricción hostile?
3. Replay histórico DNA (n=11) a `$3.45 / $5 / $10 / $25`
4. Estrés: primer miss arruina el micro vs sobrevive a `$25`
5. Probe opcional del libro vivo (`--live-book`)

## Cómo correr

```bash
# local / VPS (SAFE — no órdenes)
python3 -m polymarket.research.local_lab.wallet_take_reality_sim \
  --balance 3.4482 --balances 3.4482,5,10,25 --live-book
```

Salida:

- `polymarket/data_local/local_lab/wallet_take_reality/latest.json`
- `polymarket/data_local/local_lab/wallet_take_reality/LATEST.md`

## Lectura rápida (wallet ~$3.45)

| Evento | Resultado típico |
|--------|------------------|
| Take DNA sized ~$3 | Ejecutable |
| Win limpio | Equity ≈ `$5.45` (+~$2) |
| Miss total | Equity ≈ `$0.45` → **ruin** (<$2 arm) |
| 1er miss en path @ $3.45 | Halt |
| 1er miss en path @ $25 | Sigue y puede recuperar |

El replay base hereda WR research (muestra pequeña, optimista). Usa `loss_stress` para el caso realista de miss.

## Informe de viabilidad

Para el informe ejecutivo completo (MC, adequacy, scorecard GO/CONDITIONAL/NO-GO):

```bash
python3 -m polymarket.research.local_lab.ladder_viability_report \
  --balance 3.4482 --mc-reps 2500 --live-book --write-docs
```

Ver también [`VIABILIDAD_LADDER.md`](VIABILIDAD_LADDER.md).

