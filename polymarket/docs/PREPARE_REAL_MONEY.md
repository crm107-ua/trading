# Prepare Real Money Battery

**UTC:** `2026-08-10T11:00:32.520318+00:00`
**Postura:** `WATCH_ONLY`
**Viabilidad:** `RESEARCH_ONLY`
**Rearm:** `NOT_READY`

Mecanismo de ingresos testeado en sim. Rearme a dinero real AÚN NO autorizado (evidencia/capital).

## Steps

- `polymarket.research.local_lab.simulate_real_income` ok=True exit=0 err=None
- `polymarket.research.local_lab.wallet_take_reality_sim` ok=True exit=0 err=None
- `polymarket.research.local_lab.ladder_viability_report` ok=True exit=0 err=None
- `polymarket.research.local_lab.rearm_income_gate` ok=False exit=2 err=None

Acción: Mantener WATCH_ONLY. Acumular takes DNA. No activar auto-execute. No depositar solo por MC.

## Forward watch (live books)

Telemetría en `data_local/local_lab/vps_runs/telemetry/`. Ejemplo 2026-08-10:

- HK Aug-11: basket **0.579** (gap 7.9¢), max_leg 0.45, underdispersion fail → REJECT
- Shanghai Aug-12: basket **0.690** (gap 19¢) → REJECT lejos de DNA

Mejoras ops (no DNA): recheck +30s/+90s en near-miss ≤5–8¢; digest+scan cada ~30 min.

Ver [`PROFESSIONAL_PREP.md`](PROFESSIONAL_PREP.md).
