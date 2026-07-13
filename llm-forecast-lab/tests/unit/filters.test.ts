import { describe, expect, test } from "vitest";
import type { EvalFrozen } from "../../src/config.js";
import { marketDurationDays, passesDuration, passesSelectionFilters } from "../../src/ingest/filters.js";
import type { GammaMarket } from "../../src/ingest/gamma.js";

const evalFrozenStub = {
  protocol: {
    selection: {
      minLiquidityProxy: 1000,
      includeCategories: [] as string[],
      excludeCategories: [] as string[],
      dateRange: { resolutionFrom: "2024-01-01", resolutionTo: "2026-12-31" },
      minMarketDurationDays: 7,
      excludeAmbiguousResolution: true
    }
  }
} as EvalFrozen;

describe("market duration filter", () => {
  test("excludes 5m BTC window", () => {
    const m: GammaMarket = {
      id: "1",
      question: "Bitcoin Up or Down 2:00PM-2:05PM ET",
      outcomes: '["Yes","No"]',
      startDate: "2024-06-01T18:00:00Z",
      endDate: "2024-06-01T18:05:00Z",
      liquidityNum: 5000,
      outcomePrices: '["1","0"]'
    };
    expect(marketDurationDays(m)).toBeLessThan(1);
    expect(passesDuration(m, evalFrozenStub)).toBe(false);
    expect(passesSelectionFilters(m, evalFrozenStub)).toBe(false);
  });

  test("keeps multi-week political market", () => {
    const m: GammaMarket = {
      id: "2",
      question: "Will X win?",
      outcomes: '["Yes","No"]',
      startDate: "2024-01-01T00:00:00Z",
      endDate: "2024-03-01T00:00:00Z",
      liquidityNum: 5000,
      outcomePrices: '["0","1"]'
    };
    expect(passesDuration(m, evalFrozenStub)).toBe(true);
  });
});
