# Upwork — propuesta archetype B (retrieval / hallucination)

**Versión:** v3 — inglés completo · 2026-07-13  
**Adaptación por job:** [`UPWORK_ADAPT_PROMPT.md`](UPWORK_ADAPT_PROMPT.md)  
**Estrategia:** 3 propuestas hiperadaptadas/semana · no genéricas · primeros 5–10 jobs definen JSS  
**Audit:** $95 fijo (48h, diagnosis + fix list). En jobs $800+ considerar ancla $150.

---

## Template (copiar/pegar)

**Subject:** Your retrieval problem is probably chunking + eval — not the model

Hi [Name],

You mentioned [paste exact phrase from their post — e.g. "answers aren't grounded in our docs" / "chatbot makes things up"]. In my experience that's almost always a retrieval pipeline issue: chunk boundaries splitting context, top-k set too low, or no reranking — not a model swap.

How I'd approach it: audit your current ingestion (chunk size, overlap, metadata), add hybrid retrieval (vector + keyword via pgvector or your existing store), layer a reranker over the top-20 candidates, and build a small golden set (~50 queries) with groundedness checks before touching the prompt. I work in TypeScript/Node end-to-end — no Python sidecar unless you already have one.

Relevant work: I build eval-first — before touching prompts or models, I set up a small golden set with pass/fail criteria so we can measure whether retrieval actually improved instead of guessing. Most RAG "fixes" fail because nobody measured the baseline.

One question before scoping: do you have a labeled set of "good answers" today, or would building that eval set be part of the first deliverable?

I can start with a fixed $95 pipeline audit (deliverable: written diagnosis + prioritized fix list, 48h turnaround) before committing to a full fix.

Best,  
[Your name]

---

## Búsqueda Upwork (15 min)

| Filtro | Valor |
|--------|-------|
| Keywords | `RAG`, `LangChain`, `vector`, `TypeScript`, `hallucination`, `retrieval` |
| Category | AI & Machine Learning → AI Apps & Integration |
| Posted | Últimos 7 días |
| Evitar | "ChatGPT wrapper", custom LLM training, budget <$300 |

---

## Qué NO poner en la propuesta

- Origen trading / crypto / "killed 8 hypotheses"
- Mezcla español/inglés en el cuerpo enviado al cliente
- Audit sin precio fijo
