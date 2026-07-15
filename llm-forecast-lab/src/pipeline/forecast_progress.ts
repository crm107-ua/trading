import fs from "node:fs";
import path from "node:path";
import type Database from "better-sqlite3";
import { loadEvalFrozen } from "../config.js";

export type ForecastProgress = {
  savedAt: string;
  pipeline: string;
  modelId: string;
  expected: number;
  total: number;
  ok: number;
  failed: number;
  skippedExisting: number;
  pct: number;
  lastCreatedAt: string | null;
  resumeCommand: string;
};

export function countExpectedForecasts(
  db: Database.Database,
  args: { pipeline: string; modelId: string }
): number {
  const rows = db
    .prepare(
      `
    select count(*) as n
    from questions q
    join market_snapshots ms on ms.question_id = q.id
    where q.canary_only = 1
       or q.id in (select question_id from run_questions)
  `
    )
    .get() as { n: number };
  return rows.n;
}

export function readForecastProgress(
  db: Database.Database,
  args: { pipeline: string; modelId: string }
): ForecastProgress {
  const expected = countExpectedForecasts(db, args);
  const total = (
    db
      .prepare("select count(*) as n from forecasts where pipeline = @p and model_id = @m")
      .get({ p: args.pipeline, m: args.modelId }) as { n: number }
  ).n;
  const ok = (
    db
      .prepare(
        "select count(*) as n from forecasts where pipeline = @p and model_id = @m and forecast_failed = 0 and p is not null"
      )
      .get({ p: args.pipeline, m: args.modelId }) as { n: number }
  ).n;
  const failed = total - ok;
  const last = (
    db.prepare("select created_at from forecasts where pipeline = @p order by created_at desc limit 1").get({
      p: args.pipeline
    }) as { created_at: string } | undefined
  )?.created_at;
  const meta = db.prepare("select v from meta where k = 'forecast_skipped_existing'").get() as
    | { v: string }
    | undefined;
  const skippedExisting = meta ? Number(meta.v) : 0;

  return {
    savedAt: new Date().toISOString(),
    pipeline: args.pipeline,
    modelId: args.modelId,
    expected,
    total,
    ok,
    failed,
    skippedExisting,
    pct: expected === 0 ? 0 : Number(((total / expected) * 100).toFixed(1)),
    lastCreatedAt: last ?? null,
    resumeCommand:
      "node dist/cli.js forecast --pipeline naive --mode live --model meta/llama-3.3-70b-instruct --provider nvidia"
  };
}

export function writeForecastCheckpoint(
  db: Database.Database,
  args: { pipeline: string; modelId: string; outPath?: string }
): ForecastProgress {
  const progress = readForecastProgress(db, args);
  const json = JSON.stringify(progress, null, 2) + "\n";
  db.prepare("insert into meta(k,v) values('forecast_progress',@v) on conflict(k) do update set v=excluded.v").run({
    v: json
  });
  const out = args.outPath ?? path.join(process.cwd(), "output", "forecast_state.json");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, json);
  return progress;
}

export function persistForecastRunMeta(
  db: Database.Database,
  args: {
    pipeline: string;
    modelId: string;
    skippedExisting: number;
    purgedForecasts: number;
    fresh: boolean;
  }
): void {
  loadEvalFrozen("./config");
  const payload = {
    updatedAt: new Date().toISOString(),
    pipeline: args.pipeline,
    modelId: args.modelId,
    fresh: args.fresh,
    purgedForecasts: args.purgedForecasts,
    skippedExisting: args.skippedExisting
  };
  db.prepare("insert into meta(k,v) values('forecast_run',@v) on conflict(k) do update set v=excluded.v").run({
    v: JSON.stringify(payload)
  });
  db.prepare(
    "insert into meta(k,v) values('forecast_skipped_existing',@v) on conflict(k) do update set v=excluded.v"
  ).run({ v: String(args.skippedExisting) });
  writeForecastCheckpoint(db, { pipeline: args.pipeline, modelId: args.modelId });
}
