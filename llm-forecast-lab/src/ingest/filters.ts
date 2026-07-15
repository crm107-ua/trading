import type { EvalFrozen } from "../config.js";
import { GammaMarket, isBinaryYesNoOutcomes } from "./gamma.js";

export function marketDurationDays(m: GammaMarket): number | null {
  const end = m.endDate ? Date.parse(String(m.endDate)) : NaN;
  const startRaw = m.startDate ?? m.createdAt;
  const start = startRaw ? Date.parse(String(startRaw)) : NaN;
  if (!Number.isFinite(end) || !Number.isFinite(start) || end <= start) return null;
  return (end - start) / (24 * 3600 * 1000);
}

export function passesDateRange(m: GammaMarket, evalFrozen: EvalFrozen): boolean {
  if (!m.endDate) return false;
  const resTs = Date.parse(String(m.endDate));
  const from = Date.parse(evalFrozen.protocol.selection.dateRange.resolutionFrom);
  const to = Date.parse(evalFrozen.protocol.selection.dateRange.resolutionTo);
  return Number.isFinite(resTs) && resTs >= from && resTs <= to;
}

export function passesDuration(m: GammaMarket, evalFrozen: EvalFrozen): boolean {
  const minDays = evalFrozen.protocol.selection.minMarketDurationDays;
  const dur = marketDurationDays(m);
  if (dur === null) return false;
  return dur >= minDays;
}

export function passesCanaryCandidateFilters(
  m: GammaMarket,
  evalFrozen: EvalFrozen,
  resolutionFrom: string,
  resolutionTo: string
): boolean {
  if (!isBinaryYesNoOutcomes(m.outcomes) || !m.endDate) return false;
  if (Boolean(m.isDisputed ?? m.isResolutionDisputed ?? m.hasDispute ?? false)) return false;
  const resTs = Date.parse(String(m.endDate));
  const from = Date.parse(resolutionFrom);
  const to = Date.parse(`${resolutionTo}T23:59:59.999Z`);
  if (!Number.isFinite(resTs) || resTs < from || resTs > to) return false;
  const dur = marketDurationDays(m);
  if (dur === null || dur < evalFrozen.protocol.selection.minMarketDurationDays) return false;
  const liq = Number(m.liquidityNum ?? m.volumeNum ?? 0);
  if (liq < evalFrozen.protocol.selection.minLiquidityProxy) return false;
  return true;
}

export function passesSelectionFilters(m: GammaMarket, evalFrozen: EvalFrozen): boolean {
  if (!isBinaryYesNoOutcomes(m.outcomes) || !m.endDate) return false;
  if (Boolean(m.isDisputed ?? m.isResolutionDisputed ?? m.hasDispute ?? false)) return false;
  if (!passesDateRange(m, evalFrozen)) return false;
  if (!passesDuration(m, evalFrozen)) return false;
  const liq = Number(m.liquidityNum ?? m.volumeNum ?? 0);
  if (liq < evalFrozen.protocol.selection.minLiquidityProxy) return false;
  const cat = m.category ?? "";
  const inc = evalFrozen.protocol.selection.includeCategories;
  const exc = evalFrozen.protocol.selection.excludeCategories;
  if (inc.length > 0 && !inc.includes(cat)) return false;
  if (exc.length > 0 && exc.includes(cat)) return false;
  return true;
}

export type UniverseComposition = {
  raw: number;
  afterDateRange: number;
  afterBinaryYesNo: number;
  afterDuration: number;
  afterLiquidity: number;
  afterDispute: number;
  afterAllSelection: number;
  byCategory: Record<string, number>;
  durationDays: { p50: number; p90: number; max: number; min: number };
};

export function computeUniverseComposition(
  markets: GammaMarket[],
  evalFrozen: EvalFrozen
): UniverseComposition {
  const byCategory: Record<string, number> = {};
  const durations: number[] = [];
  let afterDateRange = 0;
  let afterBinaryYesNo = 0;
  let afterDuration = 0;
  let afterLiquidity = 0;
  let afterDispute = 0;
  let afterAllSelection = 0;

  for (const m of markets) {
    if (passesDateRange(m, evalFrozen)) afterDateRange += 1;
    if (!isBinaryYesNoOutcomes(m.outcomes) || !m.endDate) continue;
    afterBinaryYesNo += 1;
    if (!passesDuration(m, evalFrozen)) continue;
    afterDuration += 1;
    const dur = marketDurationDays(m);
    if (dur !== null) durations.push(dur);
    if (Number(m.liquidityNum ?? m.volumeNum ?? 0) < evalFrozen.protocol.selection.minLiquidityProxy) continue;
    afterLiquidity += 1;
    if (Boolean(m.isDisputed ?? m.isResolutionDisputed ?? m.hasDispute ?? false)) continue;
    afterDispute += 1;
    if (!passesSelectionFilters(m, evalFrozen)) continue;
    afterAllSelection += 1;
    const cat = m.category?.trim() || "OTHER";
    byCategory[cat] = (byCategory[cat] ?? 0) + 1;
  }

  durations.sort((a, b) => a - b);
  const pct = (p: number) =>
    durations.length === 0 ? 0 : durations[Math.floor(p * (durations.length - 1))] ?? 0;

  return {
    raw: markets.length,
    afterDateRange,
    afterBinaryYesNo,
    afterDuration,
    afterLiquidity,
    afterDispute,
    afterAllSelection,
    byCategory,
    durationDays: {
      p50: pct(0.5),
      p90: pct(0.9),
      min: durations.length === 0 ? 0 : durations[0] ?? 0,
      max: durations.length === 0 ? 0 : durations[durations.length - 1] ?? 0
    }
  };
}
