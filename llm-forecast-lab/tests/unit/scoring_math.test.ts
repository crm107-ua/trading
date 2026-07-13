import { describe, expect, test } from "vitest";
import { brier, logLoss } from "../../src/eval/scoring.js";
import { calibrationBins, ece } from "../../src/eval/calibration.js";

describe("scoring math", () => {
  test("brier hand values", () => {
    expect(brier(1, 1)).toBe(0);
    expect(brier(0, 1)).toBe(1);
    expect(brier(0.2, 1)).toBeCloseTo(0.64);
    expect(brier(0.2, 0)).toBeCloseTo(0.04);
  });

  test("log loss hand values", () => {
    expect(logLoss(0.5, 1)).toBeCloseTo(0.69314718056, 8);
    expect(logLoss(0.5, 0)).toBeCloseTo(0.69314718056, 8);
    expect(logLoss(0.9, 1)).toBeCloseTo(-Math.log(0.9), 8);
  });
});

describe("calibration", () => {
  test("bins handle edge p=0 and p=1", () => {
    const bins = calibrationBins({ ps: [0, 1], ys: [0, 1] });
    expect(bins[0]?.n).toBe(1);
    expect(bins[9]?.n).toBe(1);
  });

  test("ece is 0 for perfect calibration", () => {
    const bins = calibrationBins({ ps: [0.0, 1.0], ys: [0, 1] });
    expect(ece(bins)).toBeCloseTo(0);
  });
});

