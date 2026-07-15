import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { openDb } from "../../src/db.js";
import { ingestPolymarket } from "../../src/ingest/ingest.js";
import { DEFAULT_NIM_MODEL, DEFAULT_NIM_PROVIDER } from "../../src/defaults.js";
import { LlmClient } from "../../src/pipeline/client.js";
import { runNaiveForecast } from "../../src/pipeline/forecasters/naive.js";
import { scoreForecasts } from "../../src/eval/score_run.js";
import { generateReport } from "../../src/eval/report.js";

describe("golden report (fixtures, no network)", () => {
  test("produces stable verdict field", async () => {
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
    const rep = generateReport(db, { pipeline: "naive", mode: "fixtures" });

    const expected = JSON.parse(
      fs.readFileSync(path.join(process.cwd(), "tests", "golden", "expected_report.json"), "utf-8")
    ) as { verdict: string };

    expect(rep.verdict).toEqual(expected.verdict);
  });
});
