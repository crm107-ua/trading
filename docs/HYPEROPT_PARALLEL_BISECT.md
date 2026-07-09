# Bisect hyperopt paralelo (`-j > 1`)

Post-MeanRevBB. **No bisectar sección a sección del config** hasta separar los dos ejes.

## Lección: `hyperopt_pickle_check` no es oráculo

`cloudpickle.dumps` del closure puede fallar (`_thread.lock`) **incluso donde hyperopt `-j 2` completa sin error**. El probe sirve para inspección (`--inspect`, recursion, `__closure__`), no para predecir si el batch paralelo funcionará.

**Test decisivo:** hyperopt real con `-j 2` y pocos epochs (`scripts/probe_vanilla_hyperopt_parallel.ps1`).

## Matriz 2×2

| | Config vainilla | Config lab (`base.json` + `backtest.json`) |
|---|---|---|
| **SampleStrategy** (templates) | ✅ A — pasa `-j 2` | ⏳ B — `probe_hyperopt_bisect.ps1 -Cell lab-sample` |
| **MeanRevBB** (user_data/strategies) | ⏳ C — `probe_hyperopt_bisect.ps1 -Cell meanrev-vanilla` | ❌ D — falla `-j 2` (confirmado) |

Tracebacks completos por celda: `user_data/validation_reports/hyperopt_bisect/cell_*.log`

### Interpretación

- **B falla** → culpable = **config del laboratorio** (no `user_data/strategies`).
- **B pasa, C falla** → culpable = **import/código** (estado global de módulo; no viaja en la instancia pero sí en el proceso que loky clona).
- **B y C fallan** → causas apiladas (config + código); comparar tracebacks C vs D.

Solo entonces bisectar **dentro del eje culpable**.

### Tracebacks

No basta PASS/FAIL. Si C falla, el log dice *qué* objeto no serializa. Si C y D muestran el **mismo** error → causa única; si **distinto** → dos problemas independientes.

## Grep config — hipótesis, no causa

`backtest.json` está limpio (`StaticPairList` solo). El pipeline mergea `base.json` + `backtest.json`; en base figuran `telegram.enabled: true` y `api_server.enabled: true`.

**Cautela epistemológica:** no está demostrado que telegram/api_server **arranquen** en runmode hyperopt/backtest. Freqtrade suele no inicializar RPC en esos modos; si es así, los flags serían **inertes** durante hyperopt y el `_thread.lock` vendría de otro sitio (ccxt/exchange threads, loky, imports globales).

- El **grep genera hipótesis**; la **celda B la juzga**.
- Si B **pasa**, telegram/api_server quedan **exonerados como causa del pickle** (la higiene de apagarlos en configs de optimización sigue siendo debida — deuda de intención declarada vs runmode).

Candidatos alternativos si B pasa: threads ccxt, loky, estado global en imports de `user_data/strategies`.

## Higiene config (post-MeanRevBB)

Overrides `telegram`/`api_server` disabled en config de optimización — no altera lógica de trading; MeanRevBB (`-j 1`, config previo) sigue siendo comparable con el batch posterior.

**Metadatos:** cada `report.json` incluye `config_files` y `config_merged_sha256` — cualquier cambio de config entre runs queda visible sin depender de memoria humana.

## Eje código (`user_data/strategies`)

`_base.py` no usa structlog (`logging.getLogger` a nivel de módulo). Si C falla, revisar imports freqtrade/talib, `quant_core`, `@informative`, handlers globales.

## Secuencia

1. MeanRevBB → `report.json` → calibrar → congelar veredicto (commit).
2. Celdas B y C con tracebacks (`probe_hyperopt_bisect.ps1`).
3. Higiene config si procede; anotar nuevo `config_merged_sha256` en reports siguientes.
4. Batch de las cuatro con `-j` uniforme por estrategia.

La calibración no espera al bisect.
