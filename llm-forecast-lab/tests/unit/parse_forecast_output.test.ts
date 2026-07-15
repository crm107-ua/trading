import { describe, expect, test } from "vitest";
import { parseForecastOutput } from "../../src/pipeline/schema.js";

describe("parseForecastOutput", () => {
  test("parses JSON wrapped in markdown fences", () => {
    const text = '```\n{"p":0.06,"key_factors":["a"],"base_rate_considered":"b","confidence_note":"c"}\n```';
    const out = parseForecastOutput(text);
    expect(out?.p).toBe(0.06);
  });
});
