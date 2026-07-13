import { describe, expect, test } from "vitest";
import { openDb } from "../../src/db.js";
import { generateReport } from "../../src/eval/report.js";

describe("leakage canary trip => EVAL_INVALID", () => {
  test("forces EVAL_INVALID when canary brier is suspiciously low", () => {
    const db = openDb("fixtures");

    // Ensure meta doesn't trip other integrity checks first.
    db.prepare("insert into meta(k,v) values('ingested','1000') on conflict(k) do update set v=excluded.v").run();
    db.prepare("insert into meta(k,v) values('ingest_rejects','0') on conflict(k) do update set v=excluded.v").run();

    // Insert minimal question + forecast for a model in config/models.json.
    // Make resolution BEFORE cutoff so it lands in canary set.
    db.prepare(
      `
      insert into questions (id, source, question_text, description, category, resolution_date, resolved_outcome, ambiguous_resolution, liquidity_proxy)
      values ('canary_q', 'polymarket', 'Canary question', '', 'example', '2024-05-20T00:00:00.000Z', 1, 0, 999999)
    `
    ).run();

    // Forecast row: perfect p=1 and score brier=0 for that canary.
    db.prepare(
      `
      insert into forecasts (
        id, question_id, pipeline, model_id, provider, horizon_hours, forecast_ts,
        prompt_hash, cache_key, retrieval,
        p, key_factors_json, base_rate_considered, confidence_note,
        forecast_failed, raw_response_json, created_at
      )
      values (
        'canary_f', 'canary_q', 'naive', 'gpt-4.1-mini', 'openai', 24, '2024-05-19T00:00:00.000Z',
        'h', 'k', 'none',
        1.0, '[]', 'x', 'x',
        0, '{}', '2026-01-01T00:00:00.000Z'
      )
    `
    ).run();

    db.prepare(`insert into scores (forecast_id, y, brier, log_loss) values ('canary_f', 1, 0.0, 0.0)`).run();

    const rep = generateReport(db, { pipeline: "naive", mode: "fixtures" });
    expect(rep.verdict).toBe("EVAL_INVALID");
    expect(rep.reason).toBe("leakage_suspected");
  });
});

