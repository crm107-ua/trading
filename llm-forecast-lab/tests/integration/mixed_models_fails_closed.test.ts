import { describe, expect, test } from "vitest";
import { openDb } from "../../src/db.js";
import { generateReport } from "../../src/eval/report.js";

describe("mixed_models guard", () => {
  test("EVAL_INVALID when pipeline has multiple model_ids", () => {
    const db = openDb("fixtures");
    db.prepare("delete from forecasts").run();
    for (const [qid, mid, fid] of [
      ["m_q1", "gpt-4.1-mini", "m_f1"],
      ["m_q2", "other-model", "m_f2"]
    ] as const) {
      db.prepare(
        `insert into questions (id, source, question_text, resolution_date, resolved_outcome, ambiguous_resolution, liquidity_proxy)
         values (@id, 'polymarket', @qt, '2026-01-01T00:00:00.000Z', 1, 0, 999999)`
      ).run({ id: qid, qt: `Q ${qid}` });
      db.prepare(
        `insert into forecasts (id, question_id, pipeline, model_id, provider, horizon_hours, forecast_ts,
          prompt_hash, cache_key, retrieval, p, forecast_failed, created_at)
         values (@fid, @qid, 'naive', @mid, 'openai', 24, '2025-12-31T00:00:00.000Z', 'h', 'c', 'none', 0.5, 0, '2026-01-01')`
      ).run({ fid, qid, mid });
    }
    const rep = generateReport(db, { pipeline: "naive", mode: "fixtures" });
    expect(rep.verdict).toBe("EVAL_INVALID");
    expect(rep.reason).toBe("mixed_models");
  });
});
