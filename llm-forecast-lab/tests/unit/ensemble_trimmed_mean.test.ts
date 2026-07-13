import { describe, expect, test } from "vitest";
import { trimmedMean } from "../../src/pipeline/forecasters/ensemble.js";

describe("trimmedMean", () => {
  test("computes trimmed mean", () => {
    expect(trimmedMean([0, 0, 1, 1, 1], 0.2)).toBeCloseTo((0 + 1 + 1) / 3);
  });
});

