# Smoke test local (Windows) -- NOT official phase A

Official 30-day clock starts on **Hetzner PM2** into `phase_a_16/` only.

---

## Reglas

| Regla | Detalle |
|-------|---------|
| Datos smoke | Solo `data_local/smoke_test/` (`POLY_DATASET=smoke_test`) |
| No mezclar | Borrar `phase_a_16/` local antes/después del smoke |
| `validate_phase_a.py` | Rechaza `smoke_test` (exit 3) |
| Duración | ~90 min (cruzar rotación horaria + varias ventanas 5m) |

---

## Windows prep

```powershell
$env:PYTHONUTF8 = "1"
# permanente: setx PYTHONUTF8 1  (nueva terminal)

powercfg /change standby-timeout-ac 0
```

---

## Opción A -- orquestador (recomendado)

Incluye kill/relaunch clob a los 20 min + validación al final:

```powershell
cd C:\Users\carom\Desktop\trading
$env:PYTHONUTF8 = "1"
python -m polymarket.research.collectors.run_smoke_test
```

## Opción B -- dos terminales manual

```powershell
$env:POLY_DATASET = "smoke_test"
$env:POLY_MANIFEST_INTERVAL_S = "60"
python -m polymarket.research.collectors.daemon_btc_feed
```

```powershell
$env:POLY_DATASET = "smoke_test"
$env:POLY_MANIFEST_INTERVAL_S = "60"
python -m polymarket.research.collectors.daemon_clob_recorder
```

---

## Criterios (8)

1. ~90 min, rotación horaria de ficheros
2. >=1 market switch en manifest (pre-suscribe ~45s; ver PREREG corrección 2026-07-13)
3. `btc/` y `clob/` jsonl.gz legibles, JSON valido, recv_ts_ns monotono
4. Alineacion reloj btc vs clob (mismo host)
5. Manifest actualizado; gap tras kill/relaunch
6. `health_check.py` OK vivo / FAIL parado
7. Top-10 niveles por lado en snapshots clob
8. Cobertura ventana 5m: span basado en `window_start` observados (no wall-clock). Warm-up excluido solo al inicio.

### Nota auditoría (2026-07-13)

Durante el hardening del validador se probaron 3 definiciones de denominador de cobertura:

- `14/17` → wall-clock (dependía de cuándo corrías el validador)
- `14/22` → wall-clock más largo (mismo problema, más evidente)
- `14/14` → **definición final**: `expected_windows` por span `min..max(window_start)` observados

Los dos primeros se descartaron por ser manipulables (inflables) post-parada. La definición final será la base del anclaje oficial (`phase_start_utc`/`phase_end_utc` + warm-up) en fase A.

```powershell
python -m polymarket.research.collectors.smoke_validate
```

---

## Tras PASS

```powershell
Remove-Item -Recurse -Force polymarket\data_local\smoke_test
Remove-Item -Recurse -Force polymarket\data_local\phase_a_16 -ErrorAction SilentlyContinue
```

Desplegar Hetzner; reloj oficial = primera hora prod validada (checks 3-5).
