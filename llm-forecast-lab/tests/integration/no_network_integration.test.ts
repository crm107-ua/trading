import { describe, expect, test } from "vitest";
import { openDb } from "../../src/db.js";
import { ingestPolymarket } from "../../src/ingest/ingest.js";
import { LlmClient } from "../../src/pipeline/client.js";
import { runNaiveForecast } from "../../src/pipeline/forecasters/naive.js";
import { scoreForecasts } from "../../src/eval/score_run.js";
import { generateReport } from "../../src/eval/report.js";

describe("integration (fixtures, no network)", () => {
  test("full pipeline runs with no external calls", async () => {
    const db = openDb("fixtures");
    await ingestPolymarket(db, { mode: "fixtures" });
    const client = new LlmClient({ noNetwork: "deny" });
    const fr = await runNaiveForecast({
      db,
      client,
      modelId: "gpt-4.1-mini",
      provider: "openai",
      pipeline: "naive",
      mode: "fixtures"
    });
    expect(fr.forecasts).toBeGreaterThan(0);
    scoreForecasts(db);
    const rep = generateReport(db, { pipeline: "naive", mode: "fixtures" });
    expect(rep.verdict).toBeTruthy();
  });
});

