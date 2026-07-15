import type Database from "better-sqlite3";
import type { EvalFrozen } from "../config.js";
import {
  fetchJsonWithRetry,
  GammaMarket,
  GammaMarketSchema,
  GAMMA_BASE_URL
} from "./gamma.js";
import { z } from "zod";

const GammaKeysetResponse = z.object({
  markets: z.array(GammaMarketSchema).optional(),
  next_cursor: z.string().nullable().optional()
});

const FLUSH_META_EVERY_PAGES = 1;
const CHUNKS_DONE_META = "gamma_keyset_chunks_done";
const ACTIVE_CHUNK_META = "gamma_keyset_active_chunk";
const ACTIVE_CHUNK_PAGES_META = "gamma_keyset_active_chunk_pages";

export type KeysetProgress = {
  chunksDone: number;
  chunksTotal: number;
  activeChunk: string | null;
  activeChunkPages: number;
  activeChunkPagesEst: number | null;
  keysetPct: number;
  unique: number;
  pages: number;
  complete: boolean;
};

function meanDoneChunkPagesEst(db: Database.Database, done: Set<string>): number {
  if (done.size === 0) return 400;
  let sum = 0;
  let n = 0;
  for (const id of done) {
    const raw = metaGet(db, chunkPagesEstKey(id));
    if (raw) {
      sum += Number(raw);
      n += 1;
    }
  }
  return n === 0 ? 400 : Math.ceil(sum / n);
}

function refreshActiveChunkPagesEst(db: Database.Database, chunkId: string, pagesAdded: number): void {
  const done = readChunksDone(db);
  const meanDone = meanDoneChunkPagesEst(db, done);
  const prev = Number(metaGet(db, chunkPagesEstKey(chunkId)) ?? "0");
  const slack = Math.max(100, Math.ceil(Math.max(meanDone, pagesAdded) * 0.15));
  const next = Math.max(prev, meanDone, pagesAdded + slack);
  metaSet(db, chunkPagesEstKey(chunkId), String(next));
}

export function readKeysetProgress(db: Database.Database, from: string, to: string): KeysetProgress {
  const chunks = monthChunks(from, to);
  const done = readChunksDone(db);
  const complete = metaGet(db, "gamma_keyset_complete") === "true";
  const unique = Number(
    (db.prepare("select count(*) as n from gamma_markets_raw").get() as { n: number }).n
  );
  const pages = Number(metaGet(db, "gamma_keyset_pages") ?? "0");
  const activeChunk = metaGet(db, ACTIVE_CHUNK_META);
  const activeChunkPages = Number(metaGet(db, ACTIVE_CHUNK_PAGES_META) ?? "0");
  const meanDone = meanDoneChunkPagesEst(db, done);
  const estRaw = activeChunk ? metaGet(db, chunkPagesEstKey(activeChunk)) : null;
  const activeChunkPagesEst = estRaw ? Number(estRaw) : null;

  if (complete) {
    return {
      chunksDone: chunks.length,
      chunksTotal: chunks.length,
      activeChunk: null,
      activeChunkPages: 0,
      activeChunkPagesEst: null,
      keysetPct: 100,
      unique,
      pages,
      complete: true
    };
  }

  const chunkWeight = 100 / chunks.length;
  let keysetPct = done.size * chunkWeight;
  if (activeChunk && !done.has(activeChunk)) {
    const slack = Math.max(100, Math.ceil(Math.max(meanDone, activeChunkPages) * 0.15));
    const est = Math.max(meanDone, activeChunkPagesEst ?? meanDone, activeChunkPages + slack, 50);
    keysetPct += chunkWeight * Math.min(0.98, activeChunkPages / est);
  }
  keysetPct = Number(Math.min(99.9, keysetPct).toFixed(1));

  return {
    chunksDone: done.size,
    chunksTotal: chunks.length,
    activeChunk,
    activeChunkPages,
    activeChunkPagesEst: activeChunk && !done.has(activeChunk)
      ? Math.max(meanDone, activeChunkPagesEst ?? meanDone, activeChunkPages + Math.max(100, Math.ceil(meanDone * 0.15)), 50)
      : activeChunkPagesEst,
    keysetPct,
    unique,
    pages,
    complete: false
  };
}

function chunkPagesEstKey(chunkId: string): string {
  return `gamma_keyset_chunk_pages_est_${chunkId}`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** Monthly [from,to] slices inside the frozen resolution window (shallow keyset per chunk). */
export function monthChunks(fromIso: string, toIso: string): Array<{ id: string; from: string; to: string }> {
  const start = new Date(fromIso);
  const end = new Date(toIso);
  const out: Array<{ id: string; from: string; to: string }> = [];
  const cur = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), 1));
  const endMonth = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), 1));
  while (cur <= endMonth) {
    const y = cur.getUTCFullYear();
    const m = cur.getUTCMonth();
    const chunkStart = new Date(Date.UTC(y, m, 1));
    const chunkEnd = new Date(Date.UTC(y, m + 1, 0, 23, 59, 59, 999));
    const from = chunkStart.toISOString().slice(0, 10);
    const to = chunkEnd.toISOString().slice(0, 10);
    const id = `${y}-${String(m + 1).padStart(2, "0")}`;
    out.push({ id, from, to });
    cur.setUTCMonth(cur.getUTCMonth() + 1);
  }
  return out;
}

function readChunksDone(db: Database.Database): Set<string> {
  const raw = metaGet(db, CHUNKS_DONE_META);
  if (!raw) return new Set();
  try {
    return new Set(JSON.parse(raw) as string[]);
  } catch {
    return new Set();
  }
}

function writeChunksDone(db: Database.Database, done: Set<string>): void {
  metaSet(db, CHUNKS_DONE_META, JSON.stringify([...done].sort()));
}

async function fetchOneKeysetRange(args: {
  gammaBaseUrl: string;
  from: string;
  to: string;
  pagePauseMs: number;
  onPage?: (info: {
    page: number;
    pageSize: number;
    total: number;
    resumed: boolean;
    progress?: KeysetProgress;
  }) => void;
  db: Database.Database;
  pagesSoFar: number;
  resumed: boolean;
  scopeFrom: string;
  scopeTo: string;
  activeChunkId: string;
}): Promise<{ pagesAdded: number; dedupedUnique: number }> {
  let cursor: string | null = null;
  let pagesAdded = 0;

  while (true) {
    let url =
      `${args.gammaBaseUrl}/markets/keyset?closed=true&limit=100&order=end_date&ascending=true` +
      `&end_date_min=${encodeURIComponent(args.from)}` +
      `&end_date_max=${encodeURIComponent(args.to)}`;
    if (cursor) url += `&after_cursor=${encodeURIComponent(cursor)}`;

    const body = GammaKeysetResponse.parse(
      await fetchJsonWithRetry(url, { pagePauseMs: args.pagePauseMs })
    );
    const page = body.markets ?? [];
    if (page.length === 0) break;

    upsertGammaPage(args.db, page);
    pagesAdded += 1;
    const pages = args.pagesSoFar + pagesAdded;
    const unique = Number(
      (args.db.prepare("select count(*) as n from gamma_markets_raw").get() as { n: number }).n
    );

    cursor = body.next_cursor ?? null;
    if (pages % FLUSH_META_EVERY_PAGES === 0) {
      metaSet(args.db, "gamma_keyset_pages", String(pages));
      metaSet(args.db, "gamma_keyset_unique", String(unique));
      metaSet(args.db, ACTIVE_CHUNK_PAGES_META, String(pagesAdded));
      refreshActiveChunkPagesEst(args.db, args.activeChunkId, pagesAdded);
    }

    const progress = readKeysetProgress(args.db, args.scopeFrom, args.scopeTo);
    args.onPage?.({ page: pages, pageSize: page.length, total: unique, resumed: args.resumed, progress });

    if (!cursor) break;
  }

  const dedupedUnique = Number(
    (args.db.prepare("select count(*) as n from gamma_markets_raw").get() as { n: number }).n
  );
  return { pagesAdded, dedupedUnique };
}

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

export type KeysetIncrementalReport = {
  pagesFetched: number;
  dedupedUnique: number;
  resumed: boolean;
  completed: boolean;
};

export async function fetchMarketsViaKeysetIncremental(args: {
  db: Database.Database;
  from: string;
  to: string;
  gammaBaseUrl?: string;
  pagePauseMs?: number;
  onPage?: (info: {
    page: number;
    pageSize: number;
    total: number;
    resumed: boolean;
    progress?: KeysetProgress;
  }) => void;
}): Promise<KeysetIncrementalReport> {
  const gammaBaseUrl = args.gammaBaseUrl ?? GAMMA_BASE_URL;
  const scopeKey = `${args.from}|${args.to}`;

  const prevScope = metaGet(args.db, "gamma_keyset_scope");
  const complete = metaGet(args.db, "gamma_keyset_complete") === "true";

  if (prevScope && prevScope !== scopeKey) {
    args.db.prepare("delete from gamma_markets_raw").run();
    for (const k of [
      "gamma_keyset_scope",
      "gamma_keyset_cursor",
      "gamma_keyset_pages",
      "gamma_keyset_complete",
      "gamma_keyset_unique",
      "gamma_keyset_chunks_done"
    ]) {
      args.db.prepare("delete from meta where k = ?").run(k);
    }
  }

  if (complete && prevScope === scopeKey) {
    const unique = Number(
      (args.db.prepare("select count(*) as n from gamma_markets_raw").get() as { n: number }).n
    );
    const pages = Number(metaGet(args.db, "gamma_keyset_pages") ?? "0");
    return { pagesFetched: pages, dedupedUnique: unique, resumed: true, completed: true };
  }

  metaSet(args.db, "gamma_keyset_scope", scopeKey);
  metaSet(args.db, "gamma_keyset_complete", "false");

  const chunks = monthChunks(args.from, args.to);
  const doneChunks = readChunksDone(args.db);
  let pages = Number(metaGet(args.db, "gamma_keyset_pages") ?? "0");
  const resumed = pages > 0 || doneChunks.size > 0;

  if (resumed) {
    const uniqueNow = Number(
      (args.db.prepare("select count(*) as n from gamma_markets_raw").get() as { n: number }).n
    );
    const prog = readKeysetProgress(args.db, args.from, args.to);
    process.stderr.write(
      `gamma keyset CHUNKED RESUME (${prog.chunksDone}/${prog.chunksTotal} months, ${prog.keysetPct}% keyset, ${uniqueNow} unique)\n`
    );
  } else {
    process.stderr.write(`gamma keyset CHUNKED start (${chunks.length} months)\n`);
  }

  // Drop legacy deep cursor — monthly chunks avoid Cloudflare 403 on page ~1800+.
  args.db.prepare("delete from meta where k = 'gamma_keyset_cursor'").run();

  const pagePauseMs = args.pagePauseMs ?? 1000;

  for (const chunk of chunks) {
    if (doneChunks.has(chunk.id)) continue;
    metaSet(args.db, ACTIVE_CHUNK_META, chunk.id);
    if (!metaGet(args.db, chunkPagesEstKey(chunk.id))) {
      metaSet(args.db, chunkPagesEstKey(chunk.id), String(meanDoneChunkPagesEst(args.db, doneChunks)));
    }
    metaSet(args.db, ACTIVE_CHUNK_PAGES_META, "0");
    process.stderr.write(`gamma keyset chunk ${chunk.id} (${chunk.from}..${chunk.to})\n`);
    const r = await fetchOneKeysetRange({
      gammaBaseUrl,
      from: chunk.from,
      to: chunk.to,
      pagePauseMs,
      ...(args.onPage ? { onPage: args.onPage } : {}),
      db: args.db,
      pagesSoFar: pages,
      resumed,
      scopeFrom: args.from,
      scopeTo: args.to,
      activeChunkId: chunk.id
    });
    pages += r.pagesAdded;
    metaSet(args.db, chunkPagesEstKey(chunk.id), String(r.pagesAdded));
    doneChunks.add(chunk.id);
    writeChunksDone(args.db, doneChunks);
    metaSet(args.db, "gamma_keyset_pages", String(pages));
    metaSet(args.db, "gamma_keyset_unique", String(r.dedupedUnique));
    args.db.prepare("delete from meta where k = ?").run(ACTIVE_CHUNK_META);
    args.db.prepare("delete from meta where k = ?").run(ACTIVE_CHUNK_PAGES_META);
    const prog = readKeysetProgress(args.db, args.from, args.to);
    process.stderr.write(
      `gamma keyset chunk ${chunk.id} done — keyset ${prog.keysetPct}% (${prog.chunksDone}/${prog.chunksTotal} months)\n`
    );
    await sleep(2000);
  }

  const dedupedUnique = Number(
    (args.db.prepare("select count(*) as n from gamma_markets_raw").get() as { n: number }).n
  );
  metaSet(args.db, "gamma_keyset_pages", String(pages));
  metaSet(args.db, "gamma_keyset_unique", String(dedupedUnique));
  metaSet(args.db, "gamma_keyset_complete", "true");
  args.db.prepare("delete from meta where k = 'gamma_keyset_cursor'").run();

  return { pagesFetched: pages, dedupedUnique, resumed, completed: true };
}

export function loadGammaMarketsFromDb(db: Database.Database): GammaMarket[] {
  const rows = db
    .prepare("select payload_json from gamma_markets_raw")
    .all() as Array<{ payload_json: string }>;
  return rows.map((r) => GammaMarketSchema.parse(JSON.parse(r.payload_json)));
}
