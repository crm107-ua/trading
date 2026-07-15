import type Database from "better-sqlite3";
import { loadEvalFrozen, loadModelsConfig } from "../config.js";
import { applyRunSampling, intersectionEligibleQuestions } from "../selection/sample.js";
import { buildCompositionAnnotations } from "./composition_notes.js";
import { loadGammaMarketsFromDb } from "./gamma_keyset_ingest.js";
import { passesSelectionFilters } from "./filters.js";
import { loadFixtureQuestions } from "./fixtures.js";
import { ingestResolvedPolymarketLive, hydratePricesForQuestionIds } from "./polymarket.js";
import { upsertMarketSnapshots, upsertQuestions } from "./store.js";

export type IngestMode = "fixtures" | "live";

export type IngestReport = {
  source: "polymarket";
  mode: IngestMode;
  ingested: number;
  rejects: number;
  horizonSnapshotRejects: number;
  sampling?: {
    seed: number;
    targetQuestions: number;
    selectedQuestions: number;
    expectedHeldoutQuestions: number;
    intersectionEligible: number;
    eligibleByModel: Record<string, number>;
    stratumCounts: Record<string, number>;
  };
  universe?: {
    mode: string;
    paginationMode?: string;
    pagesFetched?: number;
    fetchedUnique?: number;
    ingestAsOf: string;
    keysetResumed?: boolean;
  };
  composition?: {
    raw: number;
    afterDateRange: number;
    afterBinaryYesNo: number;
    afterDuration: number;
    afterLiquidity: number;
    afterDispute: number;
    afterAllSelection: number;
    byCategory: Record<string, number>;
    durationDays: { p50: number; p90: number; max: number; min: number };
  };
  clob?: { fetches: number; cacheHits: number };
};

export async function ingestPolymarket(
  db: Database.Database,
  args: {
    mode: IngestMode;
    pricesForSampleOnly?: boolean;
  }
): Promise<IngestReport> {
  const evalFrozen = loadEvalFrozen("./config");
  const modelsCfg = loadModelsConfig("./config");
  const horizons = evalFrozen.protocol.horizonsHoursBeforeResolution;

  if (args.mode === "fixtures") {
    const questions = loadFixtureQuestions();
    const selected = questions.filter((q) => {
      if (evalFrozen.protocol.selection.excludeAmbiguousResolution && q.ambiguousResolution) return false;
      if (q.liquidityProxy < evalFrozen.protocol.selection.minLiquidityProxy) return false;
      return true;
    });
    const { ingested } = upsertQuestions(db, selected);
    let horizonSnapshotRejects = 0;
    for (const q of selected) {
      const r = upsertMarketSnapshots(db, q, horizons);
      horizonSnapshotRejects += r.rejects;
    }
    const sampleRep = applyRunSampling(db, evalFrozen, modelsCfg);
    db.prepare("insert into meta(k,v) values('ingested',@v) on conflict(k) do update set v=excluded.v").run({
      v: String(ingested)
    });
    db.prepare(
      "insert into meta(k,v) values('ingest_rejects',@v) on conflict(k) do update set v=excluded.v"
    ).run({ v: String(horizonSnapshotRejects) });
    db.prepare(
      "insert into meta(k,v) values('sample_report',@v) on conflict(k) do update set v=excluded.v"
    ).run({ v: JSON.stringify(sampleRep) });
    return {
      source: "polymarket",
      mode: args.mode,
      ingested,
      rejects: 0,
      horizonSnapshotRejects,
      sampling: {
        seed: sampleRep.seed,
        targetQuestions: sampleRep.targetQuestions,
        selectedQuestions: sampleRep.selectedQuestions,
        expectedHeldoutQuestions: sampleRep.expectedHeldoutQuestions,
        intersectionEligible: sampleRep.intersectionEligible,
        eligibleByModel: sampleRep.eligibleByModel,
        stratumCounts: sampleRep.stratumCounts
      }
    };
  }

  // Live: phase 1 — list universe via keyset (no CLOB yet).
  const phase1 = await ingestResolvedPolymarketLive({
    db,
    evalFrozen,
    fetchPrices: false
  });

  const allQuestions = phase1.questions;
  const { ingested: ingestedAll } = upsertQuestions(db, allQuestions);

  const sampleRep = applyRunSampling(db, evalFrozen, modelsCfg);
  const selectedIds = (
    db.prepare("select question_id from run_questions order by sort_key asc").all() as Array<{
      question_id: string;
    }>
  ).map((r) => r.question_id);

  // Phase 2 — CLOB prices for sampled questions only.
  let clobFetches = 0;
  let clobCacheHits = 0;
  let horizonSnapshotRejects = 0;
  const priceById = new Map(allQuestions.map((q) => [q.id, q]));

  if (args.pricesForSampleOnly !== false && selectedIds.length > 0) {
    const phase2 = await hydratePricesForQuestionIds({
      db,
      evalFrozen,
      questionIds: selectedIds
    });
    clobFetches = phase2.clobFetches;
    clobCacheHits = phase2.clobCacheHits;
    for (const q of phase2.questions) priceById.set(q.id, q);
  }

  const sampledQuestions = selectedIds
    .map((id) => priceById.get(id))
    .filter((q): q is NonNullable<typeof q> => Boolean(q));

  for (const q of sampledQuestions) {
    const r = upsertMarketSnapshots(db, q, horizons);
    horizonSnapshotRejects += r.rejects;
  }

  const metaSampling = JSON.stringify(sampleRep);
  const metaUniverse = JSON.stringify({
    mode: evalFrozen.protocol.universe.mode,
    paginationMode: phase1.paginationMode,
    pagesFetched: phase1.pagesFetched,
    fetchedUnique: phase1.fetchedUnique,
    ingestAsOf: evalFrozen.protocol.universe.ingestAsOf,
    keysetResumed: phase1.keysetResumed,
    universeAfterFilters: ingestedAll,
    intersectionEligible: sampleRep.intersectionEligible,
    composition: phase1.composition
  });
  if (phase1.composition) {
    db.prepare(
      "insert into meta(k,v) values('composition_report',@v) on conflict(k) do update set v=excluded.v"
    ).run({ v: JSON.stringify(phase1.composition) });
  }

  const markets = loadGammaMarketsFromDb(db);
  const eligiblePool = markets
    .filter((m) => passesSelectionFilters(m, evalFrozen))
    .map((m) => ({
      id: m.slug ?? m.id,
      category: m.category ?? null,
      resolution_date: String(m.endDate),
      liquidity_proxy: Number(m.liquidityNum ?? m.volumeNum ?? 0)
    }));
  const { eligible } = intersectionEligibleQuestions(eligiblePool, modelsCfg, evalFrozen);
  const bySlug = new Map(markets.map((m) => [m.slug ?? m.id, m]));
  const compositionAnnotations = buildCompositionAnnotations(
    eligible.map((e) => ({
      slug: e.id,
      question: bySlug.get(e.id)?.question ?? e.id,
      resolution_date: e.resolution_date
    }))
  );
  db.prepare(
    "insert into meta(k,v) values('composition_annotations',@v) on conflict(k) do update set v=excluded.v"
  ).run({ v: JSON.stringify(compositionAnnotations) });

  db.prepare("insert into meta(k,v) values('ingested',@v) on conflict(k) do update set v=excluded.v").run({
    v: String(sampledQuestions.length)
  });
  db.prepare(
    "insert into meta(k,v) values('ingest_rejects',@v) on conflict(k) do update set v=excluded.v"
  ).run({ v: String(phase1.rejects.length + horizonSnapshotRejects) });
  db.prepare(
    "insert into meta(k,v) values('sample_report',@v) on conflict(k) do update set v=excluded.v"
  ).run({ v: metaSampling });
  db.prepare(
    "insert into meta(k,v) values('universe_report',@v) on conflict(k) do update set v=excluded.v"
  ).run({ v: metaUniverse });

  const out: IngestReport = {
    source: "polymarket",
    mode: args.mode,
    ingested: sampledQuestions.length,
    rejects: phase1.rejects.length,
    horizonSnapshotRejects,
    sampling: {
      seed: sampleRep.seed,
      targetQuestions: sampleRep.targetQuestions,
      selectedQuestions: sampleRep.selectedQuestions,
      expectedHeldoutQuestions: sampleRep.expectedHeldoutQuestions,
      intersectionEligible: sampleRep.intersectionEligible,
      eligibleByModel: sampleRep.eligibleByModel,
      stratumCounts: sampleRep.stratumCounts
    },
    universe: {
      mode: evalFrozen.protocol.universe.mode,
      paginationMode: phase1.paginationMode,
      pagesFetched: phase1.pagesFetched,
      fetchedUnique: phase1.fetchedUnique,
      ingestAsOf: evalFrozen.protocol.universe.ingestAsOf,
      keysetResumed: phase1.keysetResumed
    },
    clob: { fetches: clobFetches, cacheHits: clobCacheHits }
  };
  if (phase1.composition) out.composition = phase1.composition;
  return out;
}
