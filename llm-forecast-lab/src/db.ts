import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";

export type DbMode = "fixtures" | "live";

export function dataDir(): string {
  return path.resolve(process.cwd(), "data");
}

export function dbPath(mode: DbMode): string {
  const name = mode === "fixtures" ? "fixtures.sqlite" : "lab.sqlite";
  return path.join(dataDir(), name);
}

export function openDb(mode: DbMode): Database.Database {
  fs.mkdirSync(dataDir(), { recursive: true });
  // Vitest workers: isolate DB per process to avoid Windows locks.
  const isolate = process.env.VITEST === "true";
  const p = isolate ? `${dbPath(mode)}.${process.pid}` : dbPath(mode);
  const db = new Database(p);
  db.pragma("journal_mode = WAL");
  db.pragma("foreign_keys = ON");
  migrate(db);
  return db;
}

function migrate(db: Database.Database): void {
  db.exec(`
    create table if not exists meta (
      k text primary key,
      v text not null
    );

    create table if not exists questions (
      id text primary key,
      source text not null,
      question_text text not null,
      description text,
      category text,
      resolution_date text not null,
      resolved_outcome integer not null check (resolved_outcome in (0,1)),
      ambiguous_resolution integer not null check (ambiguous_resolution in (0,1)),
      liquidity_proxy real not null default 0,
      canary_only integer not null default 0 check (canary_only in (0,1))
    );

    create table if not exists market_snapshots (
      question_id text not null references questions(id) on delete cascade,
      horizon_hours integer not null,
      snapshot_ts text not null,
      market_mid real not null check (market_mid >= 0 and market_mid <= 1),
      primary key (question_id, horizon_hours)
    );

    create table if not exists forecasts (
      id text primary key,
      question_id text not null references questions(id) on delete cascade,
      pipeline text not null,
      model_id text not null,
      provider text not null,
      horizon_hours integer not null,
      forecast_ts text not null,
      prompt_hash text not null,
      cache_key text not null,
      retrieval text not null,
      p real,
      key_factors_json text,
      base_rate_considered text,
      confidence_note text,
      forecast_failed integer not null check (forecast_failed in (0,1)),
      raw_response_json text,
      created_at text not null
    );

    create table if not exists scores (
      forecast_id text primary key references forecasts(id) on delete cascade,
      y integer not null check (y in (0,1)),
      brier real not null,
      log_loss real not null
    );

    create table if not exists gamma_markets_raw (
      slug text primary key,
      market_id text not null,
      payload_json text not null,
      fetched_at text not null
    );

    create table if not exists run_questions (
      question_id text primary key references questions(id) on delete cascade,
      stratum_key text not null,
      sort_key real not null
    );
  `);
  const qCols = db.pragma("table_info(questions)") as Array<{ name: string }>;
  if (!qCols.some((c) => c.name === "canary_only")) {
    db.exec("alter table questions add column canary_only integer not null default 0");
  }
}

