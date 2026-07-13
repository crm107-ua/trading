# Polymarket Lab

Rama de investigación separada del lab Binance — **VIVA (research)** para intento **#16**.

| Intento | Estado |
|---------|--------|
| **#15** taker FAK | `SCREEN_INVÁLIDO` — ver [`docs/SCREEN_15_INVALIDATION.md`](docs/SCREEN_15_INVALIDATION.md) |
| **#16** maker post-only | **PENDIENTE** — pre-reg [`docs/PREREG_16_POLY_MAKER_STALE.md`](docs/PREREG_16_POLY_MAKER_STALE.md) |

**Mecanismo #16:** publicar quotes bid/ask anclados a fair value BTC; cancel/replace cuando spot se mueve; ganar spread maker (0% fee); riesgo = adverse selection si actualizas lento.

---

## Fases #16 (orden fijo)

1. **A — Grabación** ≥30 días en **Hetzner + PM2** → [`docs/PHASE_A_DEPLOY.md`](docs/PHASE_A_DEPLOY.md)
2. **B — Paper maker** ≥14 días
3. **C — Screen único** con replay real

**Scope fase A:** solo BTC Up/Down **5m** (15m excluido).

---

## Comandos fase A (Hetzner)

```bash
python3 -m polymarket.research.collectors.market_discovery
pm2 start polymarket/deploy/ecosystem.config.cjs
python3 -m polymarket.research.collectors.health_check
python3 -m polymarket.research.collectors.validate_phase_a   # dia 30+
```

Config congelada: [`config/maker.json`](config/maker.json).

---

## Relación con #15

| #15 | #16 |
|-----|-----|
| Taker — compra lag ajeno | Maker — evita ser el lag |
| Fee 2% | Fee 0% |
| No evaluable | Pendiente de datos |

Ver [`docs/PROJECT_STATUS.md`](../docs/PROJECT_STATUS.md).
