# Preparación profesional — inversión real (Temperature Ladder)

**Postura vigente:** `RESEARCH_ONLY` + `WATCH_ONLY`  
**Dinero real:** OFF (`POLY_LIVE_ARMED=0`, dry-run, sin `ALLOW_REARM`)  
**Objetivo:** acumular evidencia forward OOS hasta que `rearm_income_gate` diga `READY_TO_REARM`.

## Tres procesos de investigación (VPS ES)

| PM2 | Rol | Posts |
|-----|-----|------:|
| `ladder-private-manager` | Escaneo DNA cada ~90s; telemetría rounds/near-miss/hits | No |
| `ladder-progress-watch` | Telegram EDGE + what-if live/$100/$200 | No |
| `ladder-research-improve` | Digest + candidatos de mejora cada ~30 min | No |

## Pipeline de evidencia (no confundir con sim)

1. **Histórico DNA** (`cases` → take WR80): n≈11, Wilson≈0.74 → **débil** para depósito.
2. **Forward watch** (`telemetry/dna_hits.jsonl`): hits en vivo sin post; solo cuentan a WR cuando `resolved`.
3. **Near-miss journal**: gaps a DNA (basket 0.50 / leg 0.39 / underdispersion) → mejoras ops, **no** relajar umbrales.
4. **Rearm gate**: n≥50, Wilson≥0.80, capital aguanta ≥1 miss, SAFE env, watch-only previo.

## Mejoras permitidas ahora

- **Activo:** recheck +30s si `gap_basket ≤ 0.08` (p.ej. HK 0.579) — DNA intacta.
- **Activo:** intervalo adaptativo — gap≥0.15 → ×1.5 (~135s); gap≤0.08 → 60s.
- **Activo:** heartbeat cada 10 rounds + blockers limpios en watch-only.
- Digest Telegram periódico + `IMPROVEMENT_CANDIDATES.json`.
- Priorizar ciudades con menos BLOCKED por libro (scan).

## Mejoras prohibidas hasta READY_TO_REARM

- Bajar basket max / subir leg max / quitar underdispersion.
- Depositar por Monte Carlo o WR puntual con n pequeño.
- `POLY_LADDER_ALLOW_REARM=1` o auto-execute.

## Checklist pre-inversión (orden estricto)

1. `EVIDENCE_PROGRESS.json` → n_to_go_micro = 0 y wilson_ok.
2. `python3 -m polymarket.research.local_lab.rearm_income_gate --run-income-tests --write-docs` → `READY_TO_REARM`.
3. Capital live ≥ floor (p.ej. $25 micro) y miss path no arruina.
4. Geoblock OK desde VPS ES; SAFE flags verificados.
5. Solo entonces: `POLY_LADDER_ALLOW_REARM=1` + confirmación explícita humana.

## Artefactos vivos

- `data_local/local_lab/vps_runs/telemetry/`
- `EVIDENCE_PROGRESS.json` · `DAILY_DIGEST.md` · `IMPROVEMENT_CANDIDATES.json` · `LATEST_SCAN.txt`
- Docs: `POSTURA_RESEARCH_ONLY.md` · `REARM_INCOME_GATE.md` · `PREPARE_REAL_MONEY.md`
