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

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
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
  onPage?: (info: { page: number; pageSize: number; total: number; resumed: boolean }) => void;
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
      "gamma_keyset_unique"
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

  let cursor: string | null = metaGet(args.db, "gamma_keyset_cursor");
  let pages = Number(metaGet(args.db, "gamma_keyset_pages") ?? "0");
  const resumed = pages > 0 || Boolean(cursor);

  if (resumed) {
    const uniqueNow = Number(
      (args.db.prepare("select count(*) as n from gamma_markets_raw").get() as { n: number }).n
    );
    process.stderr.write(
      `gamma keyset RESUME from page ${pages + 1} (${uniqueNow} unique in SQLite, cursor saved)\n`
    );
  }

  while (true) {
    let url =
      `${gammaBaseUrl}/markets/keyset?closed=true&limit=100&order=end_date&ascending=true` +
      `&end_date_min=${encodeURIComponent(args.from)}` +
      `&end_date_max=${encodeURIComponent(args.to)}`;
    if (cursor) url += `&after_cursor=${encodeURIComponent(cursor)}`;

    const body = GammaKeysetResponse.parse(
      await fetchJsonWithRetry(url, { pagePauseMs: args.pagePauseMs ?? 500 })
    );
    const page = body.markets ?? [];
    if (page.length === 0) break;

    upsertGammaPage(args.db, page);
    pages += 1;

    const unique = Number(
      (args.db.prepare("select count(*) as n from gamma_markets_raw").get() as { n: number }).n
    );

    cursor = body.next_cursor ?? null;
    if (pages % FLUSH_META_EVERY_PAGES === 0) {
      metaSet(args.db, "gamma_keyset_pages", String(pages));
      metaSet(args.db, "gamma_keyset_unique", String(unique));
      if (cursor) metaSet(args.db, "gamma_keyset_cursor", cursor);
      else args.db.prepare("delete from meta where k = 'gamma_keyset_cursor'").run();
    }

    args.onPage?.({ page: pages, pageSize: page.length, total: unique, resumed });

    if (!cursor) break;
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
