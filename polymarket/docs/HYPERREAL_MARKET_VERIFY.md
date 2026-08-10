> Fuente: corrida en **VPS ES** (geo OK). Cloud Agent US queda geobloqueado para posts.

# Hyperreal market verify — Polymarket LIVE

**UTC:** `2026-08-10T13:56:35.344742+00:00`
**Veredicto:** `HYPERREAL_MARKET_LIVE_OK`

Mercado live alcanzable; books CLOB leídos; DNA stack evaluado. NO hay take DNA executable ahora (normal: baskets ricos / UD stuck). Depósito runway $100 sigue válido; operar solo cuando aparezca edge.

## Checks
- `clob_reachable`=True
- `gamma_reachable`=True
- `signing_or_balance`=True
- `geoblock_ok_here`=True
- `open_events_gt0`=True
- `books_probed_ok`=True
- `dna_take_live_now`=False
- `fillable_dna_budget25_now`=False
- `near_miss_tracked`=True
- `stack_env_safe`=True

## Wallet / geo
- balance=3.4482 need_to_100=96.55
- geoblock_blocked=False msg=ok

## Latency
- `{'gamma_events': {'ok': True, 'status': 200, 'latency_ms': 86.7}, 'clob_time': {'ok': True, 'status': 200, 'latency_ms': 106.5}, 'clob_ok': {'ok': True, 'status': 200, 'latency_ms': 55.7}}`

## Stack high (live DNA scan)
- events_open=8 accepted=0 near_miss=5 ready_to_arm=False

## Closest to DNA now
- beijing 2026-08-12 basket=0.77 max_leg=0.36 ud=True gates=2/3 gap_b=0.27 skip=basket_cost=0.770>max=0.5
- beijing 2026-08-12 basket=0.77 max_leg=0.36 ud=True gates=2/3 gap_b=0.27 skip=basket_cost=0.770>max=0.5

## Book walks (muestra)
- `highest-temperature-in-beijing-on-august-11-2026` dna=False plan_bc=0.61 live_bc=0.64 fill25=False abort=True
- `highest-temperature-in-hong-kong-on-august-11-2026` dna=False plan_bc=0.609 live_bc=0.629 fill25=True abort=False
- `highest-temperature-in-shanghai-on-august-12-2026` dna=False plan_bc=0.74 live_bc=0.77 fill25=True abort=False
- `highest-temperature-in-beijing-on-august-12-2026` dna=False plan_bc=0.77 live_bc=0.8 fill25=True abort=False
- `highest-temperature-in-hong-kong-on-august-12-2026` dna=False plan_bc=0.57 live_bc=0.6 fill25=False abort=True
- `highest-temperature-in-shanghai-on-august-11-2026` dna=False plan_bc=0.9 live_bc=0.93 fill25=True abort=False

## Invariantes

- No se posta ninguna orden.
- Sin DNA take live ≠ fallo de depósito runway.
- FAK/abort-partial: si una pierna no llena, se aborta el basket.
- Auto-execute sigue bloqueado por evidencia n<50.
