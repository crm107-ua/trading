import { describe, expect, test } from "vitest";
import { openDb } from "../../src/db.js";
import { ingestPolymarket } from "../../src/ingest/ingest.js";
import { DEFAULT_NIM_MODEL, DEFAULT_NIM_PROVIDER } from "../../src/defaults.js";
import { LlmClient } from "../../src/pipeline/client.js";
import { runNaiveForecast } from "../../src/pipeline/forecasters/naive.js";
import { scoreForecasts } from "../../src/eval/score_run.js";
import { generateReport } from "../../src/eval/report.js";

function stripRunId(x: any): any {
  const { runId: _ignore, ...rest } = x;
  return rest;
}

describe("determinism", () => {
  test("two runs from cache produce identical report (excluding runId)", async () => {
    const db = openDb("fixtures");
    await ingestPolymarket(db, { mode: "fixtures" });
    const client = new LlmClient({ noNetwork: "deny" });
    await runNaiveForecast({
      db,
      client,
      modelId: DEFAULT_NIM_MODEL,
      provider: DEFAULT_NIM_PROVIDER,
      pipeline: "naive",
      mode: "fixtures"
    });
    scoreForecasts(db);
    const r1 = generateReport(db, { pipeline: "naive", mode: "fixtures" });
    const r2 = generateReport(db, { pipeline: "naive", mode: "fixtures" });
    expect(stripRunId(r1)).toEqual(stripRunId(r2));
  });
});
