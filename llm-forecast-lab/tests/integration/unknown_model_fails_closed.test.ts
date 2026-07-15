import { describe, expect, test } from "vitest";
import { openDb } from "../../src/db.js";
import { generateReport } from "../../src/eval/report.js";

describe("unknown model id fails closed", () => {
  test("EVAL_INVALID when report sees a forecast for a model missing in models.json", () => {
    const db = openDb("fixtures");
    db.prepare("insert into meta(k,v) values('ingested','1000') on conflict(k) do update set v=excluded.v").run();
    db.prepare("insert into meta(k,v) values('ingest_rejects','0') on conflict(k) do update set v=excluded.v").run();

    db.prepare(
      `
      insert into questions (id, source, question_text, description, category, resolution_date, resolved_outcome, ambiguous_resolution, liquidity_proxy)
      values ('u_q', 'polymarket', 'Unknown model question', '', 'example', '2026-01-01T00:00:00.000Z', 1, 0, 999999)
    `
    ).run();

    db.prepare(
      `
      insert into forecasts (
        id, question_id, pipeline, model_id, provider, horizon_hours, forecast_ts,
        prompt_hash, cache_key, retrieval,
        p, key_factors_json, base_rate_considered, confidence_note,
        forecast_failed, raw_response_json, created_at
      )
      values (
        'u_f', 'u_q', 'naive', 'MODEL_NOT_IN_CONFIG', 'nvidia', 24, '2025-12-31T00:00:00.000Z',
        'h', 'k', 'none',
        0.9, '[]', 'x', 'x',
        0, '{}', '2026-01-01T00:00:00.000Z'
      )
    `
    ).run();
    db.prepare(`insert into scores (forecast_id, y, brier, log_loss) values ('u_f', 1, 0.01, 0.01)`).run();

    const rep = generateReport(db, { pipeline: "naive", mode: "fixtures" });
    expect(rep.verdict).toBe("EVAL_INVALID");
    expect(rep.reason).toBe("integrity_hard_failure");
  });
});

