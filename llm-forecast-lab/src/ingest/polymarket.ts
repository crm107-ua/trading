import type Database from "better-sqlite3";
import type { EvalFrozen } from "../config.js";
import { GammaMarket, resolvedYesNoFromOutcomePrices, yesTokenId } from "./gamma.js";
import {
  fetchMarketsViaKeysetIncremental,
  loadGammaMarketsFromDb
} from "./gamma_keyset_ingest.js";
import { computeUniverseComposition, passesSelectionFilters } from "./filters.js";
import { fetchPriceHistoryCached } from "./clob_prices.js";
import type { IngestReject, Question } from "./types.js";
import { QuestionSchema } from "./types.js";

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export type LiveIngestReport = {
  paginationMode: "keyset_full" | "offset_truncated";
  pagesFetched: number;
  fetchedUnique: number;
  keysetResumed: boolean;
  composition?: ReturnType<typeof computeUniverseComposition>;
  questions: Question[];
  rejects: IngestReject[];
  clobFetches: number;
  clobCacheHits: number;
};

export async function hydratePricesForQuestionIds(args: {
  db: Database.Database;
  evalFrozen: EvalFrozen;
  questionIds: string[];
}): Promise<LiveIngestReport> {
  const rejects: IngestReject[] = [];
  const questions: Question[] = [];
  let clobFetches = 0;
  let clobCacheHits = 0;

  const rows = args.db
    .prepare(`select slug, payload_json from gamma_markets_raw`)
    .all() as Array<{ slug: string; payload_json: string }>;
  const bySlug = new Map(rows.map((r) => [r.slug, JSON.parse(r.payload_json) as GammaMarket]));
  const wanted = new Set(args.questionIds);

  for (const id of args.questionIds) {
    const m = bySlug.get(id);
    if (!m) {
      rejects.push({ reason: "missing_gamma_cache", id });
      continue;
    }
    if (!passesSelectionFilters(m, args.evalFrozen)) continue;
    const yn = resolvedYesNoFromOutcomePrices(m);
    if (!yn) {
      rejects.push({ reason: "unresolved_or_ambiguous_outcome", id: m.id });
      continue;
    }
    const tokenId = yesTokenId(m);
    if (!tokenId) {
      rejects.push({ reason: "missing_clob_token", id: m.id });
      continue;
    }
    let priceHistory: { ts: string; mid: number }[] = [];
    try {
      const { points, cacheHit } = await fetchPriceHistoryCached(tokenId);
      priceHistory = points;
      if (cacheHit) clobCacheHits += 1;
      else clobFetches += 1;
      await sleep(150);
    } catch {
      rejects.push({ reason: "clob_price_history_failed", id: m.id });
      continue;
    }
    const qid = m.slug ?? m.id;
    if (!wanted.has(qid) && !wanted.has(m.id)) continue;
    const q = QuestionSchema.safeParse({
      id: qid,
      source: "polymarket",
      questionText: m.question,
      description: m.description ?? undefined,
      category: m.category ?? undefined,
      resolution: { resolvedOutcome: yn, resolutionDate: String(m.endDate) },
      ambiguousResolution: false,
      liquidityProxy: Number(m.liquidityNum ?? m.volumeNum ?? 0),
      priceHistory
    });
    if (!q.success) {
      rejects.push({ reason: "zod_reject", id: m.id });
      continue;
    }
    questions.push(q.data);
  }

  return {
    paginationMode: "keyset_full",
    pagesFetched: 0,
    fetchedUnique: rows.length,
    keysetResumed: false,
    questions,
    rejects,
    clobFetches,
    clobCacheHits
  };
}

function marketsToQuestions(
  markets: GammaMarket[],
  evalFrozen: EvalFrozen,
  selectedIds: Set<string> | null,
  fetchPrices: boolean
): { questions: Question[]; rejects: IngestReject[]; clobFetches: number; clobCacheHits: number } {
  const rejects: IngestReject[] = [];
  const questions: Question[] = [];
  let clobFetches = 0;
  let clobCacheHits = 0;

  for (const m of markets) {
    if (!passesSelectionFilters(m, evalFrozen)) continue;
    const yn = resolvedYesNoFromOutcomePrices(m);
    if (!yn) {
      rejects.push({ reason: "unresolved_or_ambiguous_outcome", id: m.id });
      continue;
    }

    const qid = m.slug ?? m.id;
    if (selectedIds && !selectedIds.has(qid) && !selectedIds.has(m.id)) continue;

    if (fetchPrices) {
      const tokenId = yesTokenId(m);
      if (!tokenId) {
        rejects.push({ reason: "missing_clob_token", id: m.id });
        continue;
      }
      // sync path unused — hydratePricesForQuestionIds handles CLOB
    }

    const q = QuestionSchema.safeParse({
      id: qid,
      source: "polymarket",
      questionText: m.question,
      description: m.description ?? undefined,
      category: m.category ?? undefined,
      resolution: { resolvedOutcome: yn, resolutionDate: String(m.endDate) },
      ambiguousResolution: false,
      liquidityProxy: Number(m.liquidityNum ?? m.volumeNum ?? 0),
      priceHistory: []
    });
    if (!q.success) {
      rejects.push({ reason: "zod_reject", id: m.id });
      continue;
    }
    questions.push(q.data);
  }

  return { questions, rejects, clobFetches, clobCacheHits };
}

export async function ingestResolvedPolymarketLive(args: {
  db: Database.Database;
  evalFrozen: EvalFrozen;
  questionIds?: string[];
  gammaBaseUrl?: string;
  fetchPrices?: boolean;
}): Promise<LiveIngestReport> {
  const evalFrozen = args.evalFrozen;
  const from = evalFrozen.protocol.selection.dateRange.resolutionFrom;
  const to = evalFrozen.protocol.selection.dateRange.resolutionTo;

  let pages = 0;
  let fetchedUnique = 0;
  let keysetResumed = false;
  const paginationMode: "keyset_full" | "offset_truncated" = "keyset_full";

  if (evalFrozen.protocol.universe.mode === "keyset_full") {
    const r = await fetchMarketsViaKeysetIncremental({
      db: args.db,
      from,
      to,
      ...(args.gammaBaseUrl ? { gammaBaseUrl: args.gammaBaseUrl } : {}),
      pagePauseMs: 500,
      onPage: (info) => {
        if (info.page % 10 === 0) {
          const tag = info.resumed ? "resumed" : "fresh";
          process.stderr.write(`gamma keyset page ${info.page} unique=${info.total} (${tag})\n`);
        }
      }
    });
    pages = r.pagesFetched;
    fetchedUnique = r.dedupedUnique;
    keysetResumed = r.resumed;
  } else {
    throw new Error("offset_truncated ingest not implemented for live mode; use keyset_full.");
  }

  const markets = loadGammaMarketsFromDb(args.db);
  const composition = computeUniverseComposition(markets, evalFrozen);

  const selectedIds = args.questionIds ? new Set(args.questionIds) : null;
  const { questions, rejects, clobFetches, clobCacheHits } = marketsToQuestions(
    markets,
    evalFrozen,
    selectedIds,
    args.fetchPrices === true
  );

  return {
    paginationMode,
    pagesFetched: pages,
    fetchedUnique,
    keysetResumed,
    composition,
    questions,
    rejects,
    clobFetches,
    clobCacheHits
  };
}
