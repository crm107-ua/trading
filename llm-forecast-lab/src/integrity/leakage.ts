import { ModelsConfig, loadEvalFrozen, loadModelsConfig } from "../config.js";

export type Eligibility = {
  eligible: boolean;
  reason?: string;
};

export function isEligibleForModel(args: {
  resolutionDateIso: string;
  modelTrainingCutoff: string; // YYYY-MM-DD
  safetyMarginDays: number;
}): Eligibility {
  const res = Date.parse(args.resolutionDateIso);
  const cutoff = Date.parse(`${args.modelTrainingCutoff}T00:00:00.000Z`);
  if (!Number.isFinite(res) || !Number.isFinite(cutoff)) {
    return { eligible: false, reason: "bad_dates" };
  }
  const marginMs = args.safetyMarginDays * 24 * 3600 * 1000;
  // Strict eligibility: resolution_date must be strictly AFTER cutoff+margin.
  if (res <= cutoff + marginMs) {
    return { eligible: false, reason: "resolved_before_cutoff_plus_margin" };
  }
  return { eligible: true };
}

export function canarySetForModel(args: {
  allResolutionDatesIso: { id: string; resolutionDateIso: string }[];
  modelTrainingCutoff: string;
  canaryCount: number;
  minLagDays: number;
  maxLagDays: number;
}): string[] {
  // Canary window: [cutoff - maxLag, cutoff - minLag] (inclusive).
  const cutoff = Date.parse(`${args.modelTrainingCutoff}T00:00:00.000Z`);
  const minT = cutoff - args.maxLagDays * 24 * 3600 * 1000;
  const maxT = cutoff - args.minLagDays * 24 * 3600 * 1000;
  const window = args.allResolutionDatesIso
    .map((x) => ({ id: x.id, t: Date.parse(x.resolutionDateIso) }))
    .filter((x) => Number.isFinite(x.t) && x.t >= minT && x.t <= maxT)
    // closest to cutoff first (largest t)
    .sort((a, b) => b.t - a.t)
    .slice(0, args.canaryCount)
    .map((x) => x.id);
  return window;
}

export function loadIntegrityConfig(): {
  models: ModelsConfig["models"];
  safetyMarginDays: number;
  canaryEnabled: boolean;
  canaryCountPerModel: number;
  brierSuspiciousThreshold: number;
} {
  const evalFrozen = loadEvalFrozen("./config");
  const modelsCfg = loadModelsConfig("./config");
  return {
    models: modelsCfg.models,
    safetyMarginDays: evalFrozen.protocol.integrity.safetyMarginDays,
    canaryEnabled: evalFrozen.protocol.integrity.canary.enabled,
    canaryCountPerModel: evalFrozen.protocol.integrity.canary.canaryCountPerModel,
    brierSuspiciousThreshold: evalFrozen.protocol.integrity.canary.brierSuspiciousThreshold
  };
}

