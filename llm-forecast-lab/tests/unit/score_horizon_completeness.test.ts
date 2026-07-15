import { describe, expect, test } from "vitest";
import { openDb } from "../../src/db.js";
import { scoreForecasts } from "../../src/eval/score_run.js";

describe("score horizon completeness", () => {
  test("skips all forecasts for questions missing a horizon snapshot", () => {
    const db = openDb("fixtures");
    db.exec("delete from scores");
    db.prepare("delete from forecasts where question_id = 'q1'").run();
    db.prepare("delete from market_snapshots where question_id = 'q1'").run();
    db.prepare("delete from questions where id = 'q1'").run();
    db.prepare(
      `insert into questions (id, source, question_text, description, category, resolution_date, resolved_outcome, ambiguous_resolution, liquidity_proxy, canary_only)
       values ('q1', 'polymarket', 'Partial horizons', '', 'example', '2026-01-31T00:00:00.000Z', 1, 0, 5000, 0)`
    ).run();
    db.prepare(
      `insert into market_snapshots (question_id, horizon_hours, snapshot_ts, market_mid)
       values ('q1', 24, '2026-01-30T00:00:00.000Z', 0.62),
              ('q1', 72, '2026-01-28T00:00:00.000Z', 0.6)`
    ).run();
    db.prepare(
      `insert into forecasts (
        id, question_id, pipeline, model_id, provider, horizon_hours, forecast_ts,
        prompt_hash, cache_key, retrieval, p, forecast_failed, created_at
      ) values (
        'partial_q1_24', 'q1', 'naive', 'meta/llama-3.3-70b-instruct', 'nvidia', 24, '2026-01-01T00:00:00Z',
        'h1', 'k1', 'none', 0.6, 0, '2026-01-01T00:00:00Z'
      )`
    ).run();
    db.prepare(
      `insert into forecasts (
        id, question_id, pipeline, model_id, provider, horizon_hours, forecast_ts,
        prompt_hash, cache_key, retrieval, p, forecast_failed, created_at
      ) values (
        'partial_q1_72', 'q1', 'naive', 'meta/llama-3.3-70b-instruct', 'nvidia', 72, '2026-01-01T00:00:00Z',
        'h2', 'k2', 'none', 0.6, 0, '2026-01-01T00:00:00Z'
      )`
    ).run();

    const rep = scoreForecasts(db);
    expect(rep.skippedIncompleteHorizon).toBe(2);
    expect(db.prepare("select count(*) n from scores where forecast_id like 'partial_q1_%'").get()).toEqual({ n: 0 });
  });
});
