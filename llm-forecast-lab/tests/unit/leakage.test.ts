import { describe, expect, test } from "vitest";
import { canarySetForModel, isEligibleForModel } from "../../src/integrity/leakage.js";

describe("temporal integrity eligibility", () => {
  test("ineligible if resolved before cutoff+margin", () => {
    const e = isEligibleForModel({
      resolutionDateIso: "2024-06-15T00:00:00.000Z",
      modelTrainingCutoff: "2024-06-01",
      safetyMarginDays: 30
    });
    expect(e.eligible).toBe(false);
    expect(e.reason).toBe("resolved_before_cutoff_plus_margin");
  });

  test("ineligible on the exact cutoff+margin boundary (strict >)", () => {
    // cutoff 2024-06-01 + 30d margin => boundary 2024-07-01T00:00:00Z is NOT eligible
    const e = isEligibleForModel({
      resolutionDateIso: "2024-07-01T00:00:00.000Z",
      modelTrainingCutoff: "2024-06-01",
      safetyMarginDays: 30
    });
    expect(e.eligible).toBe(false);
  });

  test("eligible the day after cutoff+margin", () => {
    const e = isEligibleForModel({
      resolutionDateIso: "2024-07-02T00:00:00.000Z",
      modelTrainingCutoff: "2024-06-01",
      safetyMarginDays: 30
    });
    expect(e.eligible).toBe(true);
  });

  test("eligible if resolved after cutoff+margin", () => {
    const e = isEligibleForModel({
      resolutionDateIso: "2024-08-15T00:00:00.000Z",
      modelTrainingCutoff: "2024-06-01",
      safetyMarginDays: 30
    });
    expect(e.eligible).toBe(true);
  });
});

describe("canary selection", () => {
  test("picks canaries within [cutoff-maxLag, cutoff-minLag] window", () => {
    const ids = canarySetForModel({
      modelTrainingCutoff: "2024-06-01",
      canaryCount: 2,
      minLagDays: 60,
      maxLagDays: 365,
      allResolutionDatesIso: [
        { id: "old", resolutionDateIso: "2023-01-01T00:00:00.000Z" },
        // too close (within minLag=60d) -> excluded
        { id: "too_close", resolutionDateIso: "2024-05-20T00:00:00.000Z" },
        // inside window -> included
        { id: "in1", resolutionDateIso: "2024-03-15T00:00:00.000Z" },
        { id: "in2", resolutionDateIso: "2024-02-01T00:00:00.000Z" },
        { id: "after", resolutionDateIso: "2024-07-01T00:00:00.000Z" }
      ]
    });
    expect(ids).toEqual(["in1", "in2"]);
  });

  test("includes boundary dates (inclusive)", () => {
    // cutoff 2024-06-01, minLag=60 => maxT = 2024-04-02
    // maxLag=365 => minT = 2023-06-02
    const ids = canarySetForModel({
      modelTrainingCutoff: "2024-06-01",
      canaryCount: 10,
      minLagDays: 60,
      maxLagDays: 365,
      allResolutionDatesIso: [
        { id: "minT", resolutionDateIso: "2023-06-02T00:00:00.000Z" },
        { id: "maxT", resolutionDateIso: "2024-04-02T00:00:00.000Z" }
      ]
    });
    expect(ids).toEqual(["maxT", "minT"]);
  });
});

