# Hyperreal market verify — Polymarket LIVE

**UTC:** `2026-08-10T14:04:36.903560+00:00`
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

## Cobertura ampliada
- wide=True horizons=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] cities=['singapore', 'shanghai', 'hong-kong', 'beijing', 'seoul', 'tokyo', 'taipei', 'miami', 'wellington', 'london', 'nyc', 'new-york-city', 'chicago', 'dallas', 'austin', 'los-angeles', 'san-francisco', 'toronto', 'paris', 'berlin', 'mumbai', 'delhi', 'bangkok', 'jakarta', 'manila', 'sydney', 'melbourne']
- events_open=49 calendar_slugs=26 extras=0
- book_walks=8 (DNA cities=8 extra=0)
- fillable@$25: any=7 dna_cities=7
- closest DNA-city basket live≈0.57
- histórico cases=136 dna_takes=11 WR=1.0 Wilson95=0.7412 days=32 (2026-07-10→2026-08-10)
- streaks win=11 loss=0 basket_mean=0.3773
- histórico by_city={'singapore': 32, 'shanghai': 32, 'tokyo': 1, 'seoul': 2, 'hong-kong': 32, 'miami': 2, 'wellington': 1, 'beijing': 32, 'taipei': 2} dna_takes_by_city={'singapore': 1, 'hong-kong': 5, 'beijing': 3, 'shanghai': 2}
- histórico by_horizon={}

## Matriz de muchos casos
- open_rows únicos=49
- skip_taxonomy={'basket_cost=0.589>max=0.5+max_leg=0.400>0.39+ev=-0.0129<0.01+not_underdispersed': 1, 'basket_cost=0.590>max=0.5+not_underdispersed': 1, 'basket_cost=0.740>max=0.5+max_leg=0.420>0.39': 1, 'basket_cost=0.570>max=0.5+not_underdispersed': 1, 'basket_cost=0.770>max=0.5': 1, 'open_only': 4, 'no_sleeve_for_city': 13, 'not_volatile': 6, 'unknown_station': 18, 'basket_cost=1.010>max=0.5+max_leg=0.580>0.39+ev=-0.0806<0.01+not_underdispersed': 1, 'basket_cost=0.900>max=0.5+max_leg=0.440>0.39': 1, 'basket_cost=0.990>max=0.5+max_leg=0.530>0.39+ev=-0.0451<0.01+not_underdispersed': 1}
- gate_taxonomy (b/l/u)={'b0_l0_u0': 44, 'b0_l1_u0': 2, 'b0_l0_u1': 2, 'b0_l1_u1': 1}
- liquidity_taxonomy={'fillable_25': 7, 'abort_partial_25': 1}

### Counterfactual basket (diagnóstico; DNA live sigue ≤0.50)
- max_basket=0.5 → would_pass=0 (canonical_dna)
- max_basket=0.52 → would_pass=0 (diagnostic_only_not_live_dna)
- max_basket=0.55 → would_pass=0 (diagnostic_only_not_live_dna)
- max_basket=0.58 → would_pass=0 (diagnostic_only_not_live_dna)
- max_basket=0.6 → would_pass=0 (diagnostic_only_not_live_dna)
- max_basket=0.65 → would_pass=0 (diagnostic_only_not_live_dna)
- max_basket=0.7 → would_pass=0 (diagnostic_only_not_live_dna)
- max_basket=0.8 → would_pass=1 (diagnostic_only_not_live_dna)

### Slip stress (DNA cities + leg+UD)
- slip=0.0 → rows_ok=0
- slip=0.01 → rows_ok=0
- slip=0.02 → rows_ok=0
- slip=0.05 → rows_ok=0

### Deposit what-if (sobrevive N misses)
- dep=$100 +bal→103.45 budget=25.0 misses=1 left=78.45 survives=True
- dep=$100 +bal→103.45 budget=25.0 misses=2 left=53.45 survives=True
- dep=$100 +bal→103.45 budget=25.0 misses=3 left=28.45 survives=True
- dep=$200 +bal→203.45 budget=25.0 misses=1 left=178.45 survives=True
- dep=$200 +bal→203.45 budget=25.0 misses=2 left=153.45 survives=True
- dep=$200 +bal→203.45 budget=25.0 misses=3 left=128.45 survives=True
- dep=$500 +bal→503.45 budget=25.0 misses=1 left=478.45 survives=True
- dep=$500 +bal→503.45 budget=25.0 misses=2 left=453.45 survives=True
- dep=$500 +bal→503.45 budget=25.0 misses=3 left=428.45 survives=True

### City×day matrix (live)
- austin 2026-08-10 bc=None gates=0/3 ud=None skip=unknown_station
- austin 2026-08-11 bc=None gates=0/3 ud=None skip=unknown_station
- beijing 2026-08-10 bc=None gates=0/3 ud=None skip=open_only
- beijing 2026-08-11 bc=0.59 gates=1/3 ud=False skip=basket_cost=0.590>max=0.5+not_underdispersed
- beijing 2026-08-12 bc=0.77 gates=2/3 ud=True skip=basket_cost=0.770>max=0.5
- chicago 2026-08-10 bc=None gates=0/3 ud=None skip=unknown_station
- chicago 2026-08-11 bc=None gates=0/3 ud=None skip=unknown_station
- dallas 2026-08-10 bc=None gates=0/3 ud=None skip=unknown_station
- dallas 2026-08-11 bc=None gates=0/3 ud=None skip=unknown_station
- hong-kong 2026-08-10 bc=None gates=0/3 ud=None skip=open_only
- hong-kong 2026-08-11 bc=0.589 gates=0/3 ud=False skip=basket_cost=0.589>max=0.5+max_leg=0.400>0.39+ev=-0.0129<0.01+not_underdispersed
- hong-kong 2026-08-12 bc=0.57 gates=1/3 ud=False skip=basket_cost=0.570>max=0.5+not_underdispersed
- london 2026-08-10 bc=None gates=0/3 ud=None skip=not_volatile
- london 2026-08-11 bc=None gates=0/3 ud=None skip=not_volatile
- london 2026-08-12 bc=None gates=0/3 ud=None skip=not_volatile
- los-angeles 2026-08-10 bc=None gates=0/3 ud=None skip=unknown_station
- los-angeles 2026-08-11 bc=None gates=0/3 ud=None skip=unknown_station
- manila 2026-08-10 bc=None gates=0/3 ud=None skip=unknown_station
- manila 2026-08-11 bc=None gates=0/3 ud=None skip=unknown_station
- manila 2026-08-12 bc=None gates=0/3 ud=None skip=unknown_station
- miami 2026-08-10 bc=None gates=0/3 ud=None skip=no_sleeve_for_city
- miami 2026-08-11 bc=None gates=0/3 ud=None skip=no_sleeve_for_city
- munich 2026-08-10 bc=None gates=0/3 ud=None skip=unknown_station
- nyc 2026-08-10 bc=None gates=0/3 ud=None skip=unknown_station
- nyc 2026-08-11 bc=None gates=0/3 ud=None skip=unknown_station
- paris 2026-08-10 bc=None gates=0/3 ud=None skip=not_volatile
- paris 2026-08-11 bc=None gates=0/3 ud=None skip=not_volatile
- paris 2026-08-12 bc=None gates=0/3 ud=None skip=not_volatile
- san-francisco 2026-08-10 bc=None gates=0/3 ud=None skip=unknown_station
- san-francisco 2026-08-11 bc=None gates=0/3 ud=None skip=unknown_station
- seoul 2026-08-10 bc=None gates=0/3 ud=None skip=no_sleeve_for_city
- seoul 2026-08-11 bc=None gates=0/3 ud=None skip=no_sleeve_for_city
- seoul 2026-08-12 bc=None gates=0/3 ud=None skip=no_sleeve_for_city
- shanghai 2026-08-10 bc=None gates=0/3 ud=None skip=open_only
- shanghai 2026-08-11 bc=0.9 gates=1/3 ud=True skip=basket_cost=0.900>max=0.5+max_leg=0.440>0.39
- shanghai 2026-08-12 bc=0.74 gates=1/3 ud=True skip=basket_cost=0.740>max=0.5+max_leg=0.420>0.39
- singapore 2026-08-10 bc=None gates=0/3 ud=None skip=open_only
- singapore 2026-08-11 bc=1.01 gates=0/3 ud=False skip=basket_cost=1.010>max=0.5+max_leg=0.580>0.39+ev=-0.0806<0.01+not_underdispersed
- singapore 2026-08-12 bc=0.99 gates=0/3 ud=False skip=basket_cost=0.990>max=0.5+max_leg=0.530>0.39+ev=-0.0451<0.01+not_underdispersed
- taipei 2026-08-10 bc=None gates=0/3 ud=None skip=no_sleeve_for_city

## Wallet / geo
- balance=3.4482 need_to_100=96.55
- geoblock_blocked=False msg=ok

## Latency
- `{'gamma_events': {'ok': True, 'status': 200, 'latency_ms': 86.5}, 'clob_time': {'ok': True, 'status': 200, 'latency_ms': 108.9}, 'clob_ok': {'ok': True, 'status': 200, 'latency_ms': 51.1}}`

## Stack high (live DNA scan)
- events_open=8 accepted=0 near_miss=5 ready_to_arm=False

## Closest to DNA now
- beijing 2026-08-12 basket=0.77 max_leg=0.36 ud=True gates=2/3 gap_b=0.27 skip=basket_cost=0.770>max=0.5
- beijing 2026-08-12 basket=0.77 max_leg=0.36 ud=True gates=2/3 gap_b=0.27 skip=basket_cost=0.770>max=0.5

## Book walks (todos)
- `highest-temperature-in-hong-kong-on-august-11-2026` dna=False dna_city=True plan_bc=0.589 live_bc=0.627 fill25=True abort=False
- `highest-temperature-in-beijing-on-august-11-2026` dna=False dna_city=True plan_bc=0.59 live_bc=0.62 fill25=True abort=False
- `highest-temperature-in-shanghai-on-august-12-2026` dna=False dna_city=True plan_bc=0.74 live_bc=0.77 fill25=True abort=False
- `highest-temperature-in-hong-kong-on-august-12-2026` dna=False dna_city=True plan_bc=0.57 live_bc=0.6 fill25=False abort=True
- `highest-temperature-in-beijing-on-august-12-2026` dna=False dna_city=True plan_bc=0.77 live_bc=0.8 fill25=True abort=False
- `highest-temperature-in-shanghai-on-august-11-2026` dna=False dna_city=True plan_bc=0.9 live_bc=0.93 fill25=True abort=False
- `highest-temperature-in-singapore-on-august-12-2026` dna=False dna_city=True plan_bc=0.99 live_bc=1.02 fill25=True abort=False
- `highest-temperature-in-singapore-on-august-11-2026` dna=False dna_city=True plan_bc=1.01 live_bc=1.04 fill25=True abort=False

## Invariantes

- No se posta ninguna orden.
- Sin DNA take live ≠ fallo de depósito runway.
- FAK/abort-partial: si una pierna no llena, se aborta el basket.
- Auto-execute sigue bloqueado por evidencia n<50.
- Counterfactuales >0.50 NO cambian DNA live.
- Depósito what-if ≠ permiso de auto-execute.
- Taxonomía de skips explica por qué no hay take ahora.
