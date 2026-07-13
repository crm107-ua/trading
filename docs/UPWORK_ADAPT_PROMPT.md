# Adaptación de propuesta Upwork — archetype B (RAG / retrieval / hallucination)

**Uso:** búsqueda Upwork → pegar job completo → ejecutar este prompt.  
**Plantilla canónica:** [`UPWORK_PROPOSAL_RAG_B.md`](UPWORK_PROPOSAL_RAG_B.md)  
**Orden:** no adaptar sin job real. Rendimiento cero sin input.

---

## Prompt maestro (copiar a Cursor / chat)

```markdown
# Adaptación de propuesta Upwork — archetype B (RAG / retrieval / hallucination)

## Rol
Eres mi editor de propuestas de Upwork. Tu trabajo NO es reescribir la plantilla:
es adaptarla al job concreto con el mínimo de cambios y el máximo de especificidad.

## Plantilla canónica (v3 — no cambiar estructura ni tono)
Ver docs/UPWORK_PROPOSAL_RAG_B.md — Subject + 5 párrafos + audit + cierre.

## Job real
[pegar aquí el texto COMPLETO del job post, incluido título]
- Presupuesto mostrado: [fixed $X / hourly $X–Y / no especificado]
- Nº de propuestas ya enviadas (si Upwork lo muestra): [N]
- Preguntas de screening del cliente (si las hay): [pegar]

## Reglas de adaptación
1. **Frase 1:** cita textual del dolor del cliente entre sus propias palabras
   (máx. 12 palabras citadas). Si el post no nombra un dolor concreto de
   retrieval/hallucination → PARAR y decírmelo: quizá no es archetype B.
2. **Párrafo técnico:** ajustar SOLO los detalles que el job revela
   (su vector store, su stack, su volumen de docs). No inventar: si no lo
   dicen, mantener el genérico de la plantilla.
3. **Ancla del audit:** $95 si budget < $800 o no especificado;
   $150 si budget ≥ $800. No ofrecer audit si el job es hourly puro —
   en ese caso proponer "first 2-3 hours = diagnosis deliverable".
4. **Pregunta de cierre:** mantener la del golden set salvo que el cliente
   ya diga que tiene evals — entonces sustituir por una pregunta específica
   sobre su métrica actual.
5. **Preguntas de screening:** responderlas TODAS, concisas, en el mismo
   tono. Ninguna respuesta > 4 frases.
6. **Longitud total:** ≤ 200 palabras el cuerpo (sin contar screening).
   Inglés completo. Cero listas de frameworks, cero "I'm passionate about AI".

## Salida
1. Propuesta final lista para pegar
2. 3 líneas de justificación: qué adaptaste y por qué
3. Verificación explícita: ¿este job es realmente archetype B, o me estoy
   forzando a encajarlo? Si dudas, dilo — descartar un job malo protege el JSS.
```

---

## Condiciones de muerte del prompt (misma lógica que el lab)

| Regla | Muerte |
|-------|--------|
| **1** | Post sin dolor retrieval/hallucination nombrado → **no archetype B** → no enviar |
| **Salida 3** | Forzar encaje en B cuando es wrapper / training / otro archetype → **descartar** — protege JSS |

Mejor descartar barato que enviar caro.

---

## Filtros de búsqueda (fase 0)

| Filtro | Valor |
|--------|-------|
| Keywords | `RAG`, `LangChain`, `vector`, `TypeScript`, `hallucination`, `retrieval` |
| Posted | Últimos 7 días |
| Evitar | budgets <$300, "simple ChatGPT wrapper", custom LLM training |
| Meta | 3 propuestas hiperadaptadas/semana, no 10 genéricas |

---

## Anclas de audit

| Presupuesto job | Audit |
|-----------------|-------|
| < $800 o no especificado | **$95** fijo, 48h, diagnosis + fix list |
| ≥ $800 fixed | **$150** fijo |
| Hourly puro | Sin audit fijo → "first 2–3 hours = diagnosis deliverable" |
