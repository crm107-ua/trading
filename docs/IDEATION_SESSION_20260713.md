# Ideación de mecanismos — sesión acotada (2026-07-13)

**Modo:** papel adversarial · sin código · sin datos · coste ~1 h · cero máquina.

**Contexto:** proyecto en pausa tras 8/8 hipótesis cerradas. Restricciones: retail ~10k USDT, Binance, fees estándar, slippage ~0,5%/lado (no-majors), sin colocation ni flujo privilegiado.

**Umbral de supervivencia:** edge bruto esperado ≥ **2× fricción** del ciclo relevante (lección #14, clase C).

---

## Resultado

| Métrica | Valor |
|---------|-------|
| Candidatos evaluados | 5 |
| Supervivientes | **0** |
| Coste por muerte | ~12 min/candidato en papel |

---

## Las cinco familias del edge retail-accesible en crypto

| # | Familia | Candidato | Puerta de muerte |
|---|---------|-----------|------------------|
| 1 | Carry / convergencia | Cash-and-carry futuros con entrega | **Isomorfismo** — variante de #14; no mecanismo nuevo |
| 2 | Spreads relativos | Funding cross-sectional (4 piernas) | **Fricción** — edge < 2× coste de cuatro patas |
| 3 | Microestructura | Mean reversion post-liquidación | **Contraparte/dato** — contraparte unclear; sin OI histórico auditable |
| 4 | Arbitraje de par | Premium/discount stablecoins | **Fricción** (régimen frecuente) + **cola** (depeg en estrés) |
| 5 | Prima de riesgo | Short vol delta-hedged | **Cola no acotable** — sin condición de muerte numérica honesta pre-data |

**Mapa:** las cinco familias naturales del retail en crypto mueren por una de tres puertas — fricción, tail no acotable, o falta de contraparte/dato auditable — o por isomorfismo con hipótesis ya muerta.

---

## Criterio destacado: descarte por isomorfismo (#1)

Rechazar un candidato porque es **#14 con otra etiqueta** (contango trimestral vs funding perpetuo) evita el error clásico de reciclar mecanismos muertos. Misma estructura económica → mismo veredicto esperado → no cuenta como intento nuevo.

---

## Curva de aprendizaje del sistema (coste por hipótesis muerta)

| Fase | Ejemplo | Coste aproximado |
|------|---------|------------------|
| Validación full | #10 XSecMomentum | Semanas + WF + hyperopt |
| Fase 0 + simulador + screen | #14 Funding Carry | Días + implementación dual-leg |
| **Papel adversarial** | Esta sesión (×5) | **~1 h total, cero máquina** |

El coste por hipótesis muerta cayó **dos órdenes de magnitud** a lo largo del proyecto. Eso es curva de aprendizaje de un sistema de investigación, no racha de mala suerte.

---

## Lectura meta (registry / cierre)

> **La pausa no es fatiga sino espacio de búsqueda agotado bajo las restricciones actuales (10k, Binance retail, sin cola). Cualquier reapertura que relaje una restricción es proyecto nuevo, no iteración.**

El mapa de familias **no caduca**: con 100k, otro exchange, o estructuras con cola acotada, indica qué familias se reabren y cuáles no.

---

## Respuesta final del capítulo

**No hay edge retail-accesible bajo estas restricciones**, demostrado por protocolo propio en **8 validaciones cerradas** + **5 muertes en papel** (esta sesión).

Cierre con respuesta, no con cansancio.

---

*No genera fila #15 en el registry — es exploración pre-registry que produjo 0 candidatos dignos de pre-reg.*
