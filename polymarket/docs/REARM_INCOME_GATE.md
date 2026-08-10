# Rearm Income Gate

**UTC:** `2026-08-10T12:33:02.800217+00:00`
**Status:** `NOT_READY`

Mantener WATCH_ONLY. Acumular takes DNA. No activar auto-execute. No depositar solo por MC.

## Evidencia
- n=11 wins=11 WR_puntual=1.0 Wilson95=0.7412
- deposit_talk_ok=False · rearm_ok=False
- MC/bootstrap sobre los mismos takes NO cuenta como evidencia extra. Hace falta muestra DNA adicional (ideal OOS / forward).

## Ingeniería
- passed=True

## Income mechanism tests
- passed=True · verdict=INCOME_GENERATION_ASSURED
- Simulación ultra-realista (CLOB entry histórico + floors live + fricción). No es fill on-chain; geoblock US sigue bloqueando posts reales desde Cloud Agent.

## Capital
- balance=3.4482 · armed_after_1_miss=False

## Ops
- watch_only=True

## Blockers
- `evidence_n=11_wilson=0.7412_need_n>=50_wilson>=0.8`
- `capital_cannot_survive_1_miss`

## Cómo rearmar (solo si READY_TO_REARM)

1. Confirmar este gate en verde.
2. Depositar solo si `can_recommend_deposit`.
3. PM2: `private_manager_live.sh` (auto-execute) en lugar de watch.
4. `POLY_LADDER_REAL_CONFIRM=1` + `--i-accept-real-loss YES`.
5. Primeras sesiones: micro cap; un miss → revisar, no martingale.
