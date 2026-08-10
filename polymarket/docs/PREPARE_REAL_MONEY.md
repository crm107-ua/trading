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
