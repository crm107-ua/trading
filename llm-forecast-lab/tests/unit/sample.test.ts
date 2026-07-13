import { describe, expect, test } from "vitest";
import type { EvalFrozen } from "../../src/config.js";
import type { ModelsConfig } from "../../src/config.js";
import {
  computeSampleReport,
  intersectionEligibleQuestions,
  resolutionQuarter,
  stratifiedSelect
} from "../../src/selection/sample.js";

const evalFrozenStub = {
  protocol: {
    integrity: { safetyMarginDays: 30 },
    temporalSplit: { heldoutLastPctByResolutionDate: 0.3 },
    runSampling: {
      enabled: true,
      seed: 42,
      targetQuestions: 4,
      requireModelIntersection: true,
      strata: {
        resolutionQuarter: { enabled: true, proportional: true },
        category: { enabled: true, proportional: true, unknownBucket: "OTHER" }
      },
      minHeldoutQuestionsAfterSplit: 2
    }
  }
} as EvalFrozen;

const modelsCfgStub = {
  models: [
    { id: "m1", provider: "openai", trainingCutoff: "2024-06-01" },
    { id: "m2", provider: "openai", trainingCutoff: "2024-07-01" }
  ]
} as ModelsConfig;

describe("run sampling", () => {
  test("resolutionQuarter buckets UTC", () => {
    expect(resolutionQuarter("2024-02-15T00:00:00Z")).toBe("2024-Q1");
    expect(resolutionQuarter("2024-08-01T00:00:00Z")).toBe("2024-Q3");
  });

  test("intersection shrinks pool when cutoffs differ", () => {
    const qs = [
      { id: "a", category: "Politics", resolution_date: "2024-07-15T00:00:00Z", liquidity_proxy: 5000 },
      { id: "b", category: "Sports", resolution_date: "2024-09-15T00:00:00Z", liquidity_proxy: 5000 },
      { id: "c", category: "Politics", resolution_date: "2024-03-01T00:00:00Z", liquidity_proxy: 5000 }
    ];
    const { eligible, eligibleByModel } = intersectionEligibleQuestions(qs, modelsCfgStub, evalFrozenStub);
    expect(eligibleByModel.m1).toBe(2);
    expect(eligibleByModel.m2).toBe(1);
    expect(eligible.map((q) => q.id)).toEqual(["b"]);
  });

  test("stratifiedSelect is deterministic for fixed seed", () => {
    const pool = [
      { id: "q1", category: "A", resolution_date: "2024-01-15T00:00:00Z", liquidity_proxy: 1 },
      { id: "q2", category: "A", resolution_date: "2024-04-15T00:00:00Z", liquidity_proxy: 1 },
      { id: "q3", category: "B", resolution_date: "2024-04-20T00:00:00Z", liquidity_proxy: 1 },
      { id: "q4", category: "B", resolution_date: "2024-07-20T00:00:00Z", liquidity_proxy: 1 }
    ];
    const a = stratifiedSelect({
      pool,
      target: 3,
      seed: 99,
      strataCfg: evalFrozenStub.protocol.runSampling
    });
    const b = stratifiedSelect({
      pool,
      target: 3,
      seed: 99,
      strataCfg: evalFrozenStub.protocol.runSampling
    });
    expect(a.selected.map((q) => q.id)).toEqual(b.selected.map((q) => q.id));
    expect(a.selected).toHaveLength(3);
  });

  test("computeSampleReport bumps target for heldout floor", () => {
    const qs = Array.from({ length: 10 }, (_, i) => ({
      id: `q${i}`,
      category: "X",
      resolution_date: `2024-${String(7 + (i % 5)).padStart(2, "0")}-01T00:00:00Z`,
      liquidity_proxy: 2000
    }));
    const rep = computeSampleReport({
      questions: qs,
      evalFrozen: {
        ...evalFrozenStub,
        protocol: {
          ...evalFrozenStub.protocol,
          runSampling: { ...evalFrozenStub.protocol.runSampling, targetQuestions: 8 }
        }
      } as EvalFrozen,
      modelsCfg: { models: [{ id: "m1", provider: "openai", trainingCutoff: "2024-01-01" }] } as ModelsConfig
    });
    expect(rep.expectedHeldoutQuestions).toBeGreaterThanOrEqual(2);
  });
});
