# Por dónde seguir la investigación (hacia inversión real)

## Diagnóstico
| Bloqueo | Estado |
|---------|--------|
| Evidencia DNA | n≈11, Wilson≈0.74 → falta n≥50 / Wilson≥0.80 para **auto-execute** |
| CLOB history | vacío → **solo forward** |
| Edge live | HK gap~2¢ UD stuck; baskets vivos aún ricos |
| Capital actual | ~$3.45 no aguanta 1 miss |
| Depósito runway $100 | **`DEPOSIT_RUNWAY_GO`** (deep verify 13/13 PASS) |

## Sim / óptimo / prep
- Óptimo LT = DNA `income_wr80` → [`LONG_HORIZON_OPTIMAL.md`](LONG_HORIZON_OPTIMAL.md)
- Prep capital → [`CAPITAL_SCALE_PREP.md`](CAPITAL_SCALE_PREP.md)
- Deep verify depósito → [`DEEP_VERIFY_DEPOSIT.md`](DEEP_VERIFY_DEPOSIT.md)
- Runway → [`DEPOSIT_RUNWAY.md`](DEPOSIT_RUNWAY.md)

## Mercado live (hiperrrealista)
- `hyperreal_market_verify --write-docs` → [`HYPERREAL_MARKET_VERIFY.md`](HYPERREAL_MARKET_VERIFY.md)
- VPS: `HYPERREAL_MARKET_LIVE_OK` · books CLOB reales · sin DNA take ahora (baskets >0.50)

## Camino
1. **Puedes depositar $100 ahora** (runway, watch-only) — verificado en profundidad.
2. Forward snapshots + resolve hasta n≥50 / Wilson≥0.80.
3. Solo entonces `READY_TO_REARM` + auto-execute.
4. No aflojar DNA.

## Comandos
```bash
python -m polymarket.research.local_lab.hyperreal_market_verify --write-docs
python -m polymarket.research.local_lab.deep_verify_deposit --write-docs
python -m polymarket.research.local_lab.verify_deposit_runway --deposit 100 --write-docs
python -m polymarket.research.local_lab.long_term_robustness --write-docs
python -m polymarket.research.local_lab.resolve_forward_cases
```
