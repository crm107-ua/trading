import type Database from "better-sqlite3";
import { z } from "zod";
import type { EvalFrozen } from "../config.js";
import { loadModelsConfig } from "../config.js";
import { canarySetForModel } from "../integrity/leakage.js";
import {
  fetchJsonWithRetry,
  GammaMarket,
  GammaMarketSchema,
  GAMMA_BASE_URL
} from "./gamma.js";
import { monthChunks } from "./gamma_keyset_ingest.js";
import { passesCanaryCandidateFilters } from "./filters.js";
import { hydratePricesForQuestionIds } from "./polymarket.js";
import { upsertMarketSnapshots, upsertQuestions } from "./store.js";
import type { Question } from "./types.js";

const GammaKeysetResponse = z.object({
  markets: z.array(GammaMarketSchema).optional(),
  next_cursor: z.string().nullable().optional()
});

function metaGet(db: Database.Database, k: string): string | null {
  const row = db.prepare("select v from meta where k = ?").get(k) as { v: string } | undefined;
  return row?.v ?? null;
}

function metaSet(db: Database.Database, k: string, v: string): void {
  db.prepare("insert into meta(k,v) values(?,?) on conflict(k) do update set v=excluded.v").run(k, v);
}

function upsertGammaPage(db: Database.Database, markets: GammaMarket[]): void {
  const ins = db.prepare(`
    insert into gamma_markets_raw (slug, market_id, payload_json, fetched_at)
    values (@slug, @market_id, @payload_json, @fetched_at)
    on conflict(slug) do update set
      market_id=excluded.market_id,
      payload_json=excluded.payload_json,
      fetched_at=excluded.fetched_at
  `);
  const now = new Date().toISOString();
  const tx = db.transaction((rows: GammaMarket[]) => {
    for (const m of rows) {
      ins.run({
        slug: m.slug ?? m.id,
        market_id: m.id,
        payload_json: JSON.stringify(m),
        fetched_at: now
      });
    }
  });
  tx(markets);
}

async function fetchCanaryKeysetRange(args: {
  db: Database.Database;
  from: string;
  to: string;
  gammaBaseUrl?: string;
  pagePauseMs?: number;
}): Promise<{ pages: number }> {
  const gammaBaseUrl = args.gammaBaseUrl ?? GAMMA_BASE_URL;
  let cursor: string | null = null;
  let pages = 0;
  const pagePauseMs = args.pagePauseMs ?? 1000;

  while (true) {
    let url =
      `${gammaBaseUrl}/markets/keyset?closed=true&limit=100&order=end_date&ascending=true` +
      `&end_date_min=${encodeURIComponent(args.from)}` +
      `&end_date_max=${encodeURIComponent(args.to)}`;
    if (cursor) url += `&after_cursor=${encodeURIComponent(cursor)}`;

    const body = GammaKeysetResponse.parse(await fetchJsonWithRetry(url, { pagePauseMs }));
    const page = body.markets ?? [];
    if (page.length === 0) break;

    upsertGammaPage(args.db, page);
    pages += 1;
    cursor = body.next_cursor ?? null;
    if (!cursor) break;
  }

  return { pages };
}

export type CanaryIngestReport = {
  supplementFrom: string;
  supplementTo: string;
  pagesFetched: number;
  candidatesInWindow: number;
  selectedCanaries: number;
  ingested: number;
  horizonSnapshotRejects: number;
  clobFetches: number;
  clobCacheHits: number;
};

export async function ingestCanarySupplement(
  db: Database.Database,
  evalFrozen: EvalFrozen
): Promise<CanaryIngestReport> {
  const sup = evalFrozen.protocol.integrity.canarySupplement;
  if (!sup.enabled) {
    return {
      supplementFrom: sup.resolutionFrom,
      supplementTo: sup.resolutionTo,
      pagesFetched: 0,
      candidatesInWindow: 0,
      selectedCanaries: 0,
      ingested: 0,
      horizonSnapshotRejects: 0,
      clobFetches: 0,
      clobCacheHits: 0
    };
  }

  const modelsCfg = loadModelsConfig("./config");
  const horizons = evalFrozen.protocol.horizonsHoursBeforeResolution;
  const scopeKey = `${sup.resolutionFrom}|${sup.resolutionTo}`;
  const prevScope = metaGet(db, "gamma_canary_supplement_scope");
  const complete = metaGet(db, "gamma_canary_supplement_complete") === "true";

  let pagesFetched = Number(metaGet(db, "gamma_canary_supplement_pages") ?? "0");
  if (!complete || prevScope !== scopeKey) {
    if (prevScope && prevScope !== scopeKey) {
      db.prepare("delete from questions where canary_only = 1").run();
      for (const k of [
        "gamma_canary_supplement_scope",
        "gamma_canary_supplement_pages",
        "gamma_canary_supplement_complete"
      ]) {
        db.prepare("delete from meta where k = ?").run(k);
      }
      pagesFetched = 0;
    }
    metaSet(db, "gamma_canary_supplement_scope", scopeKey);
    metaSet(db, "gamma_canary_supplement_complete", "false");

    const chunks = monthChunks(sup.resolutionFrom, sup.resolutionTo);
    process.stderr.write(`gamma canary supplement keyset (${chunks.length} months)\n`);
    for (const chunk of chunks) {
      process.stderr.write(`gamma canary chunk ${chunk.id} (${chunk.from}..${chunk.to})\n`);
      const r = await fetchCanaryKeysetRange({
        db,
        from: chunk.from,
        to: chunk.to
      });
      pagesFetched += r.pages;
      metaSet(db, "gamma_canary_supplement_pages", String(pagesFetched));
    }
    metaSet(db, "gamma_canary_supplement_complete", "true");
  }

  const rawRows = db
    .prepare("select payload_json from gamma_markets_raw")
    .all() as Array<{ payload_json: string }>;
  const markets = rawRows.map((r) => GammaMarketSchema.parse(JSON.parse(r.payload_json)));

  const candidates = markets.filter((m) => passesCanaryCandidateFilters(m, evalFrozen, sup.resolutionFrom, sup.resolutionTo));

  const pool = candidates.map((m) => ({
    id: m.slug ?? m.id,
    resolutionDateIso: String(m.endDate)
  }));

  const target = Math.min(sup.targetCount, evalFrozen.protocol.integrity.canary.canaryCountPerModel);
  const selectedIds = new Set<string>();
  for (const model of modelsCfg.models) {
    for (const id of canarySetForModel({
      allResolutionDatesIso: pool,
      modelTrainingCutoff: model.trainingCutoff,
      canaryCount: target,
      minLagDays: evalFrozen.protocol.integrity.canary.minLagDays,
      maxLagDays: evalFrozen.protocol.integrity.canary.maxLagDays
    })) {
      selectedIds.add(id);
    }
  }

  const phase2 = await hydratePricesForQuestionIds({
    db,
    evalFrozen,
    questionIds: [...selectedIds],
    canaryWindow: { from: sup.resolutionFrom, to: sup.resolutionTo }
  });

  const questions: Question[] = [];
  for (const q of phase2.questions) {
    if (!selectedIds.has(q.id)) continue;
    questions.push(q);
  }

  const { ingested } = upsertQuestions(db, questions, { canaryOnly: true });
  let horizonSnapshotRejects = 0;
  for (const q of questions) {
    const r = upsertMarketSnapshots(db, q, horizons);
    horizonSnapshotRejects += r.rejects;
  }

  metaSet(db, "canary_supplement_report", JSON.stringify({
    supplementFrom: sup.resolutionFrom,
    supplementTo: sup.resolutionTo,
    selectedCanaries: selectedIds.size,
    ingested
  }));

  return {
    supplementFrom: sup.resolutionFrom,
    supplementTo: sup.resolutionTo,
    pagesFetched,
    candidatesInWindow: candidates.length,
    selectedCanaries: selectedIds.size,
    ingested,
    horizonSnapshotRejects,
    clobFetches: phase2.clobFetches,
    clobCacheHits: phase2.clobCacheHits
  };
}

export function canarySupplementStatus(db: Database.Database, evalFrozen: EvalFrozen): {
  complete: boolean;
  ingested: number;
  required: number;
  ok: boolean;
} {
  const sup = evalFrozen.protocol.integrity.canarySupplement;
  const ingested = (
    db.prepare("select count(*) as n from questions where canary_only = 1").get() as { n: number }
  ).n;
  const complete = metaGet(db, "gamma_canary_supplement_complete") === "true";
  const required = sup.enabled ? sup.targetCount : 0;
  return {
    complete,
    ingested,
    required,
    ok: !sup.enabled || (complete && ingested >= required)
  };
}
