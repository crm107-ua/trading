# Estado del proyecto — cierre de ciclo (2026-07-13)

**Estado:** **EN PAUSA** — sin candidato vivo para go-live.  
**Último intento:** #14 Funding Rate Carry (`run_id=20260713_screen`) → **MUERTA (D-3)**; veredicto sustantivo: *real pero no rentable*.

---

## Resumen en una frase

La pregunta «¿hay edge accesible para un retail con 10k USDT, comisiones estándar y sin información privilegiada de flujo?» tiene **respuesta empírica negativa** en este lab: los efectos que sobreviven el cribado honesto son o ilusorios, o demasiado pequeños para la escala, o ya comprimidos por el mercado.

---

## Balance del registry (ciclo 2026-07-10 → 2026-07-13)

| Métrica | Valor |
|---------|-------|
| Intentos principales cerrados | **8/8** sin estrategia desplegable |
| Candidatos que llegaron a validación full | 2 (MeanRevBB, XSecMomentum m35) |
| Veredictos full | 2× **SOBREAJUSTADA** |
| Último cierre | #14 — screen research, sin WF |

**No hay apelación pendiente.** Dry-run XSecMomentum (si sigue activo) es epílogo operativo, no revival del candidato.

---

## Taxonomía de muerte (el protocolo distingue tres causas)

| Clase | Qué significa | Ejemplos en este lab | Señal típica |
|-------|---------------|----------------------|--------------|
| **A — Sin edge / fricción** | El efecto no supera costes o no existe en el universo probado | #1–#5 screen (bruto ≤ 0); #8, #9 event studies; #11, #12 funding como señal spot | PnL bruto negativo; signo invertido; t-stats inestables |
| **B — Sobreajuste** | Edge en muestra que no replica OOS / WF con params congelados | MeanRevBB `20260709_162954`; XSecMomentum `20260712_191406` (10-V) | WFE bajo; divergencia semillas; baseline OOS > hyperopt |
| **C — Edge real, no rentable** | El mecanismo existe con modelado honesto, pero el tamaño no paga la cuenta ni el tiempo | **#14** Funding Carry delta-neutral | Carry neto > fricción; CAGR ~1,3%; mitad reciente plana; concentración |

Esta taxonomía **no es decorativa**: cada clase tiene condiciones de muerte pre-escritas distintas y implica acciones distintas (archivar vs no iterar params vs no escalar capital).

---

## Cierre #14 — lección que la predicción no anticipó

| | Predicción pre-registro | Resultado screen |
|---|-------------------------|------------------|
| **Muerte esperada** | D-1: carry neto < fricción | D-1 **no** dispara |
| **Mecanismo** | Dudoso | **Existe:** funding +1 695 USDT > fricción 926 USDT; basis −202; DD −1,5% |
| **Muerte real** | — | D-3 concentración (ETH 63,5%) + **CAGR 1,3%**; 2024–26: **+75 USDT** en ~2,5 años |

**Lectura:** no «SOBREAJUSTADA» ni «no hay carry» — **«real pero no rentable»**, con decay reciente (Sharpe 0,50 en mitad 2024–26). Solo un simulador dual-leg con funding con signo, basis separado y retorno sobre cuenta podía producir este veredicto. La expectativa de fallo acertó en *archivar*, no en el mecanismo causal exacto.

Artefacto: `research/output/funding_carry_14/20260713_screen/report.json`

---

## Activos que permanecen (transferibles)

| Activo | Contenido |
|--------|-----------|
| **Infraestructura** | Pipeline Freqtrade Docker pinneado; `run_validation` + WF + veredicto; screen protocol; pre-registro; simuladores research (`xsec_lab`, `funding_carry_lab`) |
| **Historia documentada** | Registry append-only; incidentes; calibración congelada; 8 cierres con criterios pre-fijados |
| **Narrativa de portfolio** | «Construí un sistema que mató 8 hipótesis propias con criterios pre-registrados» — rigor > backtest inflado |

---

## Condición de reapertura

El proyecto **no** acepta nuevas hipótesis salvo que se cumplan **todas**:

1. **Mecanismo nuevo** — lógica económica explicable en **2 frases**, distinta de momentum cross-sectional, mean reversion BB y funding carry ya probados.
2. **Pre-registro congelado** antes de datos — universo, señal fija, costes, condiciones de muerte, presupuesto horas y fecha límite.
3. **Presupuesto acotado** — horas/semana y fecha de archivo sin apelación (misma disciplina que #14).
4. **Un solo run** de validación por intento — sin hyperopt manual sobre umbrales de señal.

Si no se cumple → no se abre fila nueva en el registry.

---

## Operaciones en pausa

| Componente | Acción |
|------------|--------|
| Nuevas hipótesis / validación full | **Detenido** hasta reapertura explícita |
| Dry-run XSecMomentum | Epílogo opcional; no invalida cierre 10-V |
| Código / infra | Se mantiene; no requiere commits de «revival» |
| Tiempo de investigación | **Reasignado** — prioridad laboral externa (Upwork u equivalente) |

---

## Pregunta respondida (para no reabrir por olvido)

> ¿Puede un retail con ~10k, fees estándar y sin flujo privilegiado explotar edge sistemático en crypto spot/perp con este protocolo?

**Respuesta del lab:** no se encontró candidato desplegable. Los edges observados en research (#6, #7, #13) no sobreviven validación full honesta o validación de escala (#14); los screens masivos (#1–#5) no mostraron bruto positivo.

Eso es un **resultado**, no un fracaso del método.

---

*Documento de cierre de ciclo. El contador `#` del registry no se resetea; la reapertura sería intento #15+.*
