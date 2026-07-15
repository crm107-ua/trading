import { describe, expect, test, vi } from "vitest";
import { openDb } from "../../src/db.js";
import { ingestPolymarket } from "../../src/ingest/ingest.js";
import { DEFAULT_NIM_MODEL, DEFAULT_NIM_PROVIDER } from "../../src/defaults.js";
import { runNaiveForecast } from "../../src/pipeline/forecasters/naive.js";
import type { LlmClient } from "../../src/pipeline/client.js";

function mockClient(): LlmClient {
  return {
    complete: vi.fn(async () => ({
      text: '{"p":0.5,"key_factors":["a"],"base_rate_considered":"yes","confidence_note":"med"}',
      cacheHit: false
    }))
  } as unknown as LlmClient;
}

describe("forecast resume", () => {
  test("live resume skips existing rows without --fresh", async () => {
    const db = openDb("fixtures");
    await ingestPolymarket(db, { mode: "fixtures" });
    const client = mockClient();

    const r1 = await runNaiveForecast({
      db,
      client,
      modelId: DEFAULT_NIM_MODEL,
      provider: DEFAULT_NIM_PROVIDER,
      pipeline: "naive",
      mode: "fixtures"
    });
    expect(r1.forecasts).toBeGreaterThan(0);

    const before = (db.prepare("select count(*) as n from forecasts").get() as { n: number }).n;
    const r2 = await runNaiveForecast({
      db,
      client,
      modelId: DEFAULT_NIM_MODEL,
      provider: DEFAULT_NIM_PROVIDER,
      pipeline: "naive",
      mode: "fixtures"
    });
    const after = (db.prepare("select count(*) as n from forecasts").get() as { n: number }).n;

    expect(after).toBe(before);
    expect(r2.forecasts).toBe(0);
    expect(r2.skippedExisting).toBeGreaterThan(0);
  });
});
