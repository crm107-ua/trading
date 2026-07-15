import { describe, expect, test } from "vitest";
import { openDb } from "../../src/db.js";
import { DEFAULT_NIM_MODEL, DEFAULT_NIM_PROVIDER } from "../../src/defaults.js";
import { generateReport } from "../../src/eval/report.js";

describe("leakage canary tripwire (audit, not auto-invalid)", () => {
  test("low canary Brier sets auditRequired without leakage_suspected verdict", () => {
    const db = openDb("fixtures");

    db.prepare("delete from scores").run();
    db.prepare("delete from forecasts").run();
    db.prepare("delete from market_snapshots").run();
    db.prepare("delete from questions").run();

    db.prepare("insert into meta(k,v) values('ingested','1000') on conflict(k) do update set v=excluded.v").run();
    db.prepare("insert into meta(k,v) values('ingest_rejects','0') on conflict(k) do update set v=excluded.v").run();

    const horizons = [24, 72, 168];
    for (let i = 0; i < 10; i++) {
      const qid = `train_q${i}`;
      const res = `2025-${String(i + 1).padStart(2, "0")}-15T00:00:00.000Z`;
      db.prepare(
        `
        insert into questions (id, source, question_text, description, category, resolution_date, resolved_outcome, ambiguous_resolution, liquidity_proxy, canary_only)
        values (@id, 'polymarket', 'Train', '', 'example', @res, 1, 0, 999999, 0)
      `
      ).run({ id: qid, res });
      for (const h of horizons) {
        db.prepare(
          `
          insert into market_snapshots (question_id, horizon_hours, snapshot_ts, market_mid)
          values (@qid, @h, '2025-01-01T00:00:00.000Z', 0.5)
        `
        ).run({ qid, h });
        const fid = `${qid}_${h}`;
        db.prepare(
          `
          insert into forecasts (
            id, question_id, pipeline, model_id, provider, horizon_hours, forecast_ts,
            prompt_hash, cache_key, retrieval,
            p, key_factors_json, base_rate_considered, confidence_note,
            forecast_failed, raw_response_json, created_at
          )
          values (
            @fid, @qid, 'naive', @model, @provider, @h, '2025-01-01T00:00:00.000Z',
            'h', 'k', 'none',
            0.5, '[]', 'x', 'x',
            0, '{}', '2026-01-01T00:00:00.000Z'
          )
        `
        ).run({ fid, qid, h, model: DEFAULT_NIM_MODEL, provider: DEFAULT_NIM_PROVIDER });
        db.prepare(`insert into scores (forecast_id, y, brier, log_loss) values (@fid, 1, 0.25, 0.5)`).run({ fid });
      }
    }

    db.prepare(
      `
      insert into questions (id, source, question_text, description, category, resolution_date, resolved_outcome, ambiguous_resolution, liquidity_proxy, canary_only)
      values ('canary_q', 'polymarket', 'Canary question', '', 'example', '2023-09-15T00:00:00.000Z', 1, 0, 999999, 1)
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
        'canary_f', 'canary_q', 'naive', @model, @provider, 24, '2023-09-14T00:00:00.000Z',
        'h', 'k', 'none',
        1.0, '[]', 'x', 'x',
        0, '{}', '2026-01-01T00:00:00.000Z'
      )
    `
    ).run({ model: DEFAULT_NIM_MODEL, provider: DEFAULT_NIM_PROVIDER });

    db.prepare(`insert into scores (forecast_id, y, brier, log_loss) values ('canary_f', 1, 0.0, 0.0)`).run();

    const rep = generateReport(db, { pipeline: "naive", mode: "fixtures" });
    expect(rep.integrity.auditRequired).toBe(true);
    expect(rep.integrity.auditTriggers).toContain("canary_brier_low");
    expect(rep.integrity.hardIntegrityFailure).toBe(false);
    expect(rep.reason).not.toBe("leakage_suspected");
  });
});
