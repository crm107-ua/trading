# Rearm Income Gate

**UTC:** `2026-08-10T13:40:48.634481+00:00`
**Status:** `DEPOSIT_RUNWAY_GO`

PUEDES depositar $100.0 AHORA (runway, watch-only). NO armar auto-execute hasta n≥50 / Wilson≥0.80. El blocker de capital se resuelve con ese depósito; la evidencia sigue pendiente.

## Evidencia
- n=11 wins=11 WR_puntual=1.0 Wilson95=0.7412
- can_recommend_deposit=True · can_deposit_runway=True · can_auto_execute=False
- MC/bootstrap sobre los mismos takes NO cuenta como evidencia extra. Hace falta muestra DNA adicional (ideal OOS / forward).

## Ingeniería
- passed=True

## Income mechanism tests
- passed=True · verdict=INCOME_GENERATION_ASSURED
- Simulación ultra-realista (CLOB entry histórico + floors live + fricción). No es fill on-chain; geoblock US sigue bloqueando posts reales desde Cloud Agent.

## Capital
- balance=3.4482 · armed_after_1_miss=False

## Deposit runway (planificado)
- target=$100.0 status=`DEPOSIT_RUNWAY_GO`
- can_deposit_runway_watch_only=True
- planned still_armed_after_1_miss=True

## Ops
- watch_only=True

## Blockers
- `evidence_n=11_wilson=0.7412_need_n>=50_wilson>=0.8`
- `auto_execute_blocked_until_evidence`

## Cómo rearmar (solo si READY_TO_REARM)

1. Confirmar este gate en verde.
2. Depositar solo si `can_recommend_deposit`.
3. PM2: `private_manager_live.sh` (auto-execute) en lugar de watch.
4. `POLY_LADDER_REAL_CONFIRM=1` + `--i-accept-real-loss YES`.
5. Primeras sesiones: micro cap; un miss → revisar, no martingale.
