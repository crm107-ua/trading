import { loadEvalFrozen, loadModelsConfig } from "../config.js";
import { isEligibleForModel } from "../integrity/leakage.js";
import { z } from "zod";

const GammaMarketLite = z.object({
  id: z.string(),
  slug: z.string().optional(),
  question: z.string(),
  closed: z.boolean().optional(),
  endDate: z.string().nullable().optional(),
  outcomes: z.any().optional(),
  volumeNum: z.number().nullable().optional(),
  liquidityNum: z.number().nullable().optional(),
  isDisputed: z.boolean().nullable().optional(),
  isResolutionDisputed: z.boolean().nullable().optional(),
  hasDispute: z.boolean().optional(),
  category: z.string().nullable().optional()
});

const GammaKeysetResponse = z.object({
  markets: z.array(GammaMarketLite).optional(),
  next_cursor: z.string().nullable().optional()
});

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function isBinaryYesNoOutcomes(outcomes: unknown): boolean {
  try {
    const arr = typeof outcomes === "string" ? JSON.parse(outcomes) : outcomes;
    if (!Array.isArray(arr)) return false;
    const s = arr.map((x) => String(x).toLowerCase());
    return s.length === 2 && s.includes("yes") && s.includes("no");
  } catch {
    return false;
  }
}

async function fetchJsonWithRetry(url: string): Promise<unknown> {
  for (let attempt = 0; attempt < 8; attempt++) {
    const res = await fetch(url);
    if (res.status === 429 || res.status === 403) {
      await sleep(2000 * (attempt + 1));
      continue;
    }
    if (!res.ok) throw new Error(`Gamma fetch failed: ${res.status} ${await res.text()}`);
    return res.json();
  }
  throw new Error(`Gamma fetch rate-limited/blocked after retries: ${url}`);
}

async function fetchViaKeyset(args: {
  from: string;
  to: string;
}): Promise<{ markets: z.infer<typeof GammaMarketLite>[]; pages: number }> {
  const gammaBaseUrl = "https://gamma-api.polymarket.com";
  const bySlug = new Map<string, z.infer<typeof GammaMarketLite>>();
  let cursor: string | null = null;
  let pages = 0;

  while (true) {
    let url =
      `${gammaBaseUrl}/markets/keyset?closed=true&limit=100&order=end_date&ascending=true` +
      `&end_date_min=${encodeURIComponent(args.from)}` +
      `&end_date_max=${encodeURIComponent(args.to)}`;
    if (cursor) url += `&after_cursor=${encodeURIComponent(cursor)}`;

    const body = GammaKeysetResponse.parse(await fetchJsonWithRetry(url));
    const page = body.markets ?? [];
    if (page.length === 0) break;

    for (const m of page) {
      const key = m.slug ?? m.id;
      if (!bySlug.has(key)) bySlug.set(key, m);
    }

    pages += 1;
    cursor = body.next_cursor ?? null;
    if (!cursor) break;
    if (pages > 2000) break;
    await sleep(500);
  }

  return { markets: [...bySlug.values()], pages };
}

async function fetchViaOffset(args: {
  from: string;
  to: string;
}): Promise<{ markets: z.infer<typeof GammaMarketLite>[]; pages: number }> {
  // Offset pagination: Gamma returns max 100/page; hard cap offset≈2100 (422 beyond).
  // ascending=false => newest end_date first (better eligibility sample under cap).
  const gammaBaseUrl = "https://gamma-api.polymarket.com";
  const bySlug = new Map<string, z.infer<typeof GammaMarketLite>>();
  let pages = 0;

  for (let offset = 0; offset < 2100; ) {
    const url =
      `${gammaBaseUrl}/markets?closed=true&limit=100&offset=${offset}` +
      `&end_date_min=${encodeURIComponent(args.from)}` +
      `&end_date_max=${encodeURIComponent(args.to)}` +
      `&order=end_date&ascending=false`;
    const json = await fetchJsonWithRetry(url);
    const page = z.array(GammaMarketLite).parse(json);
    if (page.length === 0) break;

    for (const m of page) {
      const key = m.slug ?? m.id;
      if (!bySlug.has(key)) bySlug.set(key, m);
    }

    pages += 1;
    offset += page.length;
    if (page.length < 100) break;
    await sleep(200);
  }

  return { markets: [...bySlug.values()], pages };
}

export type ViabilityReport = {
  paginationMode: "keyset" | "offset_fallback";
  pagesFetched: number;
  fetchedUnique: number;
  binaryYesNoWithEndDate: number;
  afterSelectionFilters: number;
  afterDisputeHeuristic: number;
  eligibleByModel: Record<string, number>;
  eligibleForecastsByModel: Record<string, number>;
  heldoutEstimateByModel: Record<string, number>;
  costEstimates: {
    horizons: number;
    naiveCalls: number;
    decomposedCalls: number;
    ensembleCalls: number;
    totalCalls: number;
  };
  notes: string[];
};

export async function runViabilityCheck(): Promise<ViabilityReport> {
  const evalFrozen = loadEvalFrozen("./config");
  const modelsCfg = loadModelsConfig("./config");
  const horizons = evalFrozen.protocol.horizonsHoursBeforeResolution;
  const heldoutPct = evalFrozen.protocol.temporalSplit.heldoutLastPctByResolutionDate;

  const from = evalFrozen.protocol.selection.dateRange.resolutionFrom;
  const to = evalFrozen.protocol.selection.dateRange.resolutionTo;

  // Offset-first: ~21 páginas, cap 2100 — suficiente para viability sin disparar Cloudflare.
  // Keyset queda para ingest completo (polymarket.ts), no para este check rápido.
  let paginationMode: "keyset" | "offset_fallback" = "offset_fallback";
  let pages = 0;
  let all: z.infer<typeof GammaMarketLite>[] = [];

  try {
    const r = await fetchViaOffset({ from, to });
    all = r.markets;
    pages = r.pages;
  } catch {
    paginationMode = "keyset";
    const r = await fetchViaKeyset({ from, to });
    all = r.markets;
    pages = r.pages;
  }

  const resolved = all.filter((m) => isBinaryYesNoOutcomes(m.outcomes) && Boolean(m.endDate));

  const minLiq = evalFrozen.protocol.selection.minLiquidityProxy;
  const afterSelection = resolved.filter((m) => Number(m.liquidityNum ?? m.volumeNum ?? 0) >= minLiq);

  const afterDispute = afterSelection.filter(
    (m) => !Boolean(m.isDisputed ?? m.isResolutionDisputed ?? m.hasDispute ?? false)
  );

  const eligibleByModel: Record<string, number> = {};
  const eligibleForecastsByModel: Record<string, number> = {};
  const heldoutEstimateByModel: Record<string, number> = {};
  for (const model of modelsCfg.models) {
    let n = 0;
    for (const m of afterDispute) {
      const el = isEligibleForModel({
        resolutionDateIso: String(m.endDate),
        modelTrainingCutoff: model.trainingCutoff,
        safetyMarginDays: evalFrozen.protocol.integrity.safetyMarginDays
      });
      if (el.eligible) n += 1;
    }
    eligibleByModel[model.id] = n;
    eligibleForecastsByModel[model.id] = n * horizons.length;
    heldoutEstimateByModel[model.id] = Math.floor(n * heldoutPct);
  }

  const maxEligibleForecasts = Math.max(...Object.values(eligibleForecastsByModel), 0);
  const naiveCalls = maxEligibleForecasts;
  const decomposedCalls = maxEligibleForecasts * 3;
  const ensembleCalls =
    maxEligibleForecasts * 3 * evalFrozen.protocol.ensemble.modelsN * evalFrozen.protocol.ensemble.promptVariantsM;

  const notes: string[] = [];
  notes.push(
    "Bug histórico: stop si page.length < limit pedido; Gamma devuelve 100/página aunque limit=500."
  );
  notes.push("Parada correcta: offset += page.length; keyset hasta next_cursor=null.");
  notes.push("Offset max ~2100 (422 después); keyset /markets/keyset para archivo completo.");
  if (all.length >= 2100 && paginationMode === "offset_fallback") {
    notes.push("Muestra truncada en 2100: ejecutar ingest con keyset para universo completo.");
  }
  notes.push(`Modo usado: ${paginationMode}. Dedupe por slug. Filtros congelados post-fetch.`);
  notes.push(`heldoutEstimateByModel ≈ eligibleQuestions × ${heldoutPct}.`);

  return {
    paginationMode,
    pagesFetched: pages,
    fetchedUnique: all.length,
    binaryYesNoWithEndDate: resolved.length,
    afterSelectionFilters: afterSelection.length,
    afterDisputeHeuristic: afterDispute.length,
    eligibleByModel,
    eligibleForecastsByModel,
    heldoutEstimateByModel,
    costEstimates: {
      horizons: horizons.length,
      naiveCalls,
      decomposedCalls,
      ensembleCalls,
      totalCalls: naiveCalls + decomposedCalls + ensembleCalls
    },
    notes
  };
}
