import fs from "node:fs";
import path from "node:path";
import type Database from "better-sqlite3";
import { loadEvalFrozen, loadModelsConfig } from "../config.js";
import { marketBaselineRows } from "./baseline.js";
import type { CalibrationBin } from "./calibration.js";
import { calibrationBins, ece } from "./calibration.js";
import { bootstrapMeanDiffCi } from "./bootstrap.js";
import { canarySetForModel, isEligibleForModel } from "../integrity/leakage.js";
import { horizonCompleteQuestionIds } from "./horizon_completeness.js";

export type Verdict = "BEATS_MARKET" | "MATCHES_MARKET" | "BELOW_MARKET" | "EVAL_INVALID";

export type Report = {
  runId: string;
  verdict: Verdict;
  reason?: string | undefined;
  metrics: {
    heldoutQuestionsN: number;
    brier: number;
    brierMarket: number;
    skill: number;
    brierDiff: { mean: number; ci95: { lo: number; hi: number } };
    ece: number;
    forecastFailedRate: number;
    ingestRejectRate: number;
    incompleteHorizonQuestions?: number;
    cacheHitRate?: number;
    brierByHorizon?: Record<
      string,
      { brier: number; brierMarket: number; skill: number; forecastRowsN: number }
    >;
    calibration?: CalibrationBin[];
  };
  selection?: {
    universe: {
      mode: string;
      ingestAsOf?: string;
      paginationMode?: string;
      pagesFetched?: number;
      fetchedUnique?: number;
      universeAfterFilters?: number;
      intersectionEligible?: number;
    };
    sampling: {
      seed: number;
      targetQuestions: number;
      selectedQuestions: number;
      expectedHeldoutQuestions: number;
      strataRule: string;
      stratumCounts: Record<string, number>;
      modelIdsIntersection: string[];
      eligibleByModel: Record<string, number>;
    };
    temporalSplit: {
      heldoutPct: number;
      heldoutQuestionsN: number;
      trainQuestionsN: number;
    };
    composition?: Record<string, unknown>;
  };
  integrity: {
    /** Hard failure: eval sample contaminated (cutoff/eligibility). Forces EVAL_INVALID. */
    hardIntegrityFailure: boolean;
    /** Tripwire: manual audit required before publish. Does NOT override skill verdict. */
    auditRequired: boolean;
    auditTriggers: string[];
    /** @deprecated alias — true if auditRequired || hardIntegrityFailure */
    leakageSuspected: boolean;
    canaryBrierByModel: Record<string, number>;
    canaryScoredN?: number;
    temporalCanary?: {
      heldInQ1Skill: number;
      heldInQ1QuestionsN: number;
      heldoutSkill: number;
      triggered: boolean;
    };
    configHash: string;
    mixedModels?: boolean;
    pipelineModelIds?: string[];
  };
};

function runIdNow(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}_${pad(d.getUTCHours())}${pad(
    d.getUTCMinutes()
  )}${pad(d.getUTCSeconds())}`;
}

export function generateReport(db: Database.Database, args: { pipeline: string; mode: "fixtures" | "live" }): Report {
  const evalFrozen = loadEvalFrozen("./config");
  const modelsCfg = loadModelsConfig("./config");
  const runId = runIdNow();
  const horizons = new Set(evalFrozen.protocol.horizonsHoursBeforeResolution);
  const horizonsList = evalFrozen.protocol.horizonsHoursBeforeResolution;

  const sampleQIdsEarly = (
    db.prepare("select question_id from run_questions").all() as Array<{ question_id: string }>
  ).map((r) => r.question_id);
  const { incomplete: incompleteHorizonQuestionIds } = horizonCompleteQuestionIds(
    db,
    sampleQIdsEarly,
    horizonsList
  );
  const incompleteHorizonQuestions = incompleteHorizonQuestionIds.length;

  // ingest reject rate: from horizonSnapshotRejects in meta if present (fixtures use it).
  const meta = Object.fromEntries(
    (db.prepare("select k, v from meta").all() as Array<{ k: string; v: string }>).map((r) => [r.k, r.v])
  );
  const ingested = Number(meta["ingested"] ?? 0);
  const ingestRejects = Number(meta["ingest_rejects"] ?? 0);
  const ingestRejectRate = ingested === 0 ? 0 : ingestRejects / ingested;

  const sampleMeta = meta["sample_report"] ? (JSON.parse(meta["sample_report"]) as Record<string, unknown>) : null;
  const universeMeta = meta["universe_report"]
    ? (JSON.parse(meta["universe_report"]) as Record<string, unknown>)
    : null;
  const cacheHitRate = meta["cache_hit_rate"] ? Number(meta["cache_hit_rate"]) : undefined;

  // load forecasts + scores for pipeline
  const rows = db
    .prepare(
      `
      select f.question_id, f.horizon_hours, f.p, f.forecast_failed, f.model_id, q.resolution_date, q.resolved_outcome,
             q.canary_only, s.brier
      from forecasts f
      join questions q on q.id = f.question_id
      left join scores s on s.forecast_id = f.id
      where f.pipeline = @pipeline
      order by q.resolution_date asc
    `
    )
    .all({ pipeline: args.pipeline }) as Array<{
    question_id: string;
    horizon_hours: number;
    p: number | null;
    forecast_failed: 0 | 1;
    model_id: string;
    resolution_date: string;
    resolved_outcome: 0 | 1;
    canary_only: 0 | 1;
    brier: number | null;
  }>;

  const sampleQIds = new Set(
    (
      db.prepare("select question_id from run_questions").all() as Array<{ question_id: string }>
    ).map((r) => r.question_id)
  );
  const hasSample = sampleQIds.size > 0;
  const evalRows = rows.filter((r) => {
    if (r.canary_only) return false;
    if (hasSample) return sampleQIds.has(r.question_id);
    return true;
  });

  const baseline = marketBaselineRows(db);
  const baselineKey = new Map<string, { p: number; y: 0 | 1 }>();
  for (const b of baseline) baselineKey.set(`${b.questionId}:${b.horizonHours}`, { p: b.p, y: b.y });

  // Held-out split is by QUESTION (not by horizon rows).
  const byQ = new Map<
    string,
    {
      resolution_date: string;
      resolved_outcome: 0 | 1;
      model_id: string;
      rows: Array<{
        question_id: string;
        horizon_hours: number;
        p: number | null;
        forecast_failed: 0 | 1;
        model_id: string;
        resolution_date: string;
        resolved_outcome: 0 | 1;
        brier: number | null;
      }>;
    }
  >();
  for (const r of evalRows) {
    const cur = byQ.get(r.question_id);
    if (!cur) {
      byQ.set(r.question_id, {
        resolution_date: r.resolution_date,
        resolved_outcome: r.resolved_outcome,
        model_id: r.model_id,
        rows: [r]
      });
    } else {
      cur.rows.push(r);
    }
  }
  const qIdsSorted = [...byQ.entries()]
    .sort((a, b) => Date.parse(a[1].resolution_date) - Date.parse(b[1].resolution_date))
    .map(([qid]) => qid);
  const heldoutStartQ = Math.floor((1 - evalFrozen.protocol.temporalSplit.heldoutLastPctByResolutionDate) * qIdsSorted.length);
  const heldoutQIds = new Set(qIdsSorted.slice(heldoutStartQ));

  const aQ: number[] = [];
  const bQ: number[] = [];
  const ps: number[] = [];
  const ys: Array<0 | 1> = [];
  let heldoutQuestionsFailed = 0;

  for (const qid of heldoutQIds) {
    const q = byQ.get(qid);
    if (!q) continue;
    // Require all horizons for conservative per-question scoring.
    const rset = q.rows.filter((x) => horizons.has(x.horizon_hours));
    const haveAll = evalFrozen.protocol.horizonsHoursBeforeResolution.every((h) => rset.some((x) => x.horizon_hours === h));
    if (!haveAll) {
      heldoutQuestionsFailed += 1;
      continue;
    }
    let bad = false;
    let sumA = 0;
    let sumB = 0;
    let n = 0;
    for (const r of rset) {
      const base = baselineKey.get(`${r.question_id}:${r.horizon_hours}`);
      if (!base) {
        bad = true;
        break;
      }
      if (r.forecast_failed || r.p === null || r.brier === null) {
        bad = true;
        break;
      }
      sumA += r.brier;
      sumB += (base.p - base.y) * (base.p - base.y);
      ps.push(r.p);
      ys.push(r.resolved_outcome);
      n += 1;
    }
    if (bad || n === 0) {
      heldoutQuestionsFailed += 1;
      continue;
    }
    aQ.push(sumA / n);
    bQ.push(sumB / n);
  }

  const heldoutQuestionsN = aQ.length;
  const trainQuestionsN = Math.max(0, qIdsSorted.length - heldoutQuestionsN);
  const forecastFailedRate =
    heldoutQIds.size === 0 ? 0 : heldoutQuestionsFailed / heldoutQIds.size;

  const meanA = heldoutQuestionsN === 0 ? 0 : aQ.reduce((s, x) => s + x, 0) / heldoutQuestionsN;
  const meanB = heldoutQuestionsN === 0 ? 0 : bQ.reduce((s, x) => s + x, 0) / heldoutQuestionsN;
  const skill = meanB === 0 ? 0 : 1 - meanA / meanB;

  const ci = bootstrapMeanDiffCi({
    a: aQ,
    b: bQ,
    iterations: evalFrozen.protocol.verdict.bootstrap.iterations,
    seed: evalFrozen.protocol.verdict.bootstrap.seed,
    ci: evalFrozen.protocol.verdict.bootstrap.ci
  });

  const bins = calibrationBins({ ps, ys, bins: 10 });
  const eceVal = ece(bins);

  const brierByHorizon: NonNullable<Report["metrics"]["brierByHorizon"]> = {};
  for (const h of evalFrozen.protocol.horizonsHoursBeforeResolution) {
    const aH: number[] = [];
    const bH: number[] = [];
    for (const qid of heldoutQIds) {
      const q = byQ.get(qid);
      if (!q) continue;
      const rset = q.rows.filter((x) => horizons.has(x.horizon_hours));
      const haveAll = horizonsList.every((hh) => rset.some((x) => x.horizon_hours === hh));
      if (!haveAll) continue;
      const r = q.rows.find((x) => x.horizon_hours === h);
      if (!r || r.forecast_failed || r.p === null || r.brier === null) continue;
      const base = baselineKey.get(`${r.question_id}:${r.horizon_hours}`);
      if (!base) continue;
      aH.push(r.brier);
      bH.push((base.p - base.y) * (base.p - base.y));
    }
    const meanAH = aH.length === 0 ? 0 : aH.reduce((s, x) => s + x, 0) / aH.length;
    const meanBH = bH.length === 0 ? 0 : bH.reduce((s, x) => s + x, 0) / bH.length;
    brierByHorizon[String(h)] = {
      brier: meanAH,
      brierMarket: meanBH,
      skill: meanBH === 0 ? 0 : 1 - meanAH / meanBH,
      forecastRowsN: aH.length
    };
  }

  // Leakage canary check: compute Brier on canaries (canary_only supplement + cutoff window).
  const allResDates = (
    db.prepare("select id, resolution_date from questions").all() as Array<{
      id: string;
      resolution_date: string;
    }>
  ).map((q) => ({ id: q.id, resolutionDateIso: q.resolution_date }));

  const canaryBrierByModel: Record<string, number> = {};
  let canaryScoredN = 0;
  const auditTriggers: string[] = [];
  let hardIntegrityFailure = false;
  if (evalFrozen.protocol.integrity.canary.enabled) {
    for (const m of modelsCfg.models) {
      const canaryIds = canarySetForModel({
        allResolutionDatesIso: allResDates,
        modelTrainingCutoff: m.trainingCutoff,
        canaryCount: evalFrozen.protocol.integrity.canary.canaryCountPerModel,
        minLagDays: evalFrozen.protocol.integrity.canary.minLagDays,
        maxLagDays: evalFrozen.protocol.integrity.canary.maxLagDays
      });
      const canaryRows = rows.filter(
        (r) =>
          r.model_id === m.id &&
          r.canary_only === 1 &&
          canaryIds.includes(r.question_id)
      );
      const scored = canaryRows.filter((r) => r.brier !== null).map((r) => r.brier as number);
      canaryScoredN = Math.max(canaryScoredN, scored.length);
      const mean = scored.length === 0 ? 1 : scored.reduce((s, x) => s + x, 0) / scored.length;
      canaryBrierByModel[m.id] = mean;
      if (mean < evalFrozen.protocol.integrity.canary.brierSuspiciousThreshold) {
        auditTriggers.push("canary_brier_low");
      }
      const sup = evalFrozen.protocol.integrity.canarySupplement;
      if (sup.enabled && scored.length < sup.targetCount) {
        auditTriggers.push("canary_insufficient_n");
      }
    }
  }

  // Temporal tripwire: held-in Q1 2024 skill only (held-out poor is expected pre-run; not in trigger).
  let temporalCanary: Report["integrity"]["temporalCanary"];
  const tc = evalFrozen.protocol.integrity.temporalCanary;
  if (tc.enabled) {
    const heldInFrom = Date.parse(`${tc.heldInFrom}T00:00:00.000Z`);
    const heldInTo = Date.parse(`${tc.heldInTo}T23:59:59.999Z`);
    const trainQIds = qIdsSorted.filter((qid) => !heldoutQIds.has(qid));
    const aTrain: number[] = [];
    const bTrain: number[] = [];
    for (const qid of trainQIds) {
      const q = byQ.get(qid);
      if (!q) continue;
      const resTs = Date.parse(q.resolution_date);
      if (!Number.isFinite(resTs) || resTs < heldInFrom || resTs > heldInTo) continue;
      const rset = q.rows.filter((x) => horizons.has(x.horizon_hours));
      const haveAll = evalFrozen.protocol.horizonsHoursBeforeResolution.every((h) =>
        rset.some((x) => x.horizon_hours === h)
      );
      if (!haveAll) continue;
      let sumA = 0;
      let sumB = 0;
      let n = 0;
      for (const r of rset) {
        if (r.forecast_failed || r.p === null || r.brier === null) continue;
        const base = baselineKey.get(`${r.question_id}:${r.horizon_hours}`);
        if (!base) continue;
        sumA += r.brier;
        sumB += (base.p - base.y) * (base.p - base.y);
        n += 1;
      }
      if (n === 0) continue;
      aTrain.push(sumA / n);
      bTrain.push(sumB / n);
    }
    const meanAT = aTrain.length === 0 ? 0 : aTrain.reduce((s, x) => s + x, 0) / aTrain.length;
    const meanBT = bTrain.length === 0 ? 0 : bTrain.reduce((s, x) => s + x, 0) / bTrain.length;
    const heldInQ1Skill = meanBT === 0 ? 0 : 1 - meanAT / meanBT;
    const triggered = aTrain.length > 0 && heldInQ1Skill > tc.skillSuspiciousThreshold;
    temporalCanary = {
      heldInQ1Skill,
      heldInQ1QuestionsN: aTrain.length,
      heldoutSkill: skill,
      triggered
    };
    if (triggered) auditTriggers.push("temporal_q1_skill_high");
  }

  // Hard integrity: ineligible resolution in eval sample (not canary-only).
  for (const r of evalRows) {
    const model = modelsCfg.models.find((m) => m.id === r.model_id);
    if (!model) {
      hardIntegrityFailure = true;
      auditTriggers.push("unknown_model_in_eval");
      break;
    }
    const el = isEligibleForModel({
      resolutionDateIso: r.resolution_date,
      modelTrainingCutoff: model.trainingCutoff,
      safetyMarginDays: evalFrozen.protocol.integrity.safetyMarginDays
    });
    if (!el.eligible) {
      hardIntegrityFailure = true;
      auditTriggers.push("eval_sample_before_cutoff");
      break;
    }
  }

  const auditRequired = auditTriggers.some((t) =>
    ["canary_brier_low", "canary_insufficient_n", "temporal_q1_skill_high"].includes(t)
  );
  const leakageSuspected = auditRequired || hardIntegrityFailure;

  // Verdict logic
  const pipelineModelIds = new Set(
    (
      db
        .prepare(
          `select distinct model_id from forecasts where pipeline = @pipeline and forecast_failed = 0`
        )
        .all({ pipeline: args.pipeline }) as Array<{ model_id: string }>
    ).map((r) => r.model_id)
  );
  const mixedModels = pipelineModelIds.size > 1;

  let verdict: Verdict = "BELOW_MARKET";
  let reason: string | undefined;
  if (mixedModels) {
    verdict = "EVAL_INVALID";
    reason = "mixed_models";
  } else if (hardIntegrityFailure) {
    verdict = "EVAL_INVALID";
    reason = "integrity_hard_failure";
  } else if (evalFrozen.protocol.integrity.maxForecastFailedRate < forecastFailedRate) {
    verdict = "EVAL_INVALID";
    reason = "forecast_failed_rate_too_high";
  } else if (evalFrozen.protocol.integrity.maxIngestRejectRate < ingestRejectRate) {
    verdict = "EVAL_INVALID";
    reason = "ingest_reject_rate_too_high";
  } else if (heldoutQuestionsN < evalFrozen.protocol.integrity.canary.minEligibleHeldoutQuestions) {
    verdict = "EVAL_INVALID";
    reason = "insufficient_heldout";
  } else if (skill > 0 && ci.lo > 0) {
    verdict = "BEATS_MARKET";
  } else if (Math.abs(skill) < evalFrozen.protocol.verdict.matchSkillAbs && ci.lo <= 0 && ci.hi >= 0) {
    verdict = "MATCHES_MARKET";
  } else {
    verdict = "BELOW_MARKET";
  }

  const metrics: Report["metrics"] = {
      heldoutQuestionsN,
      brier: meanA,
      brierMarket: meanB,
      skill,
      brierDiff: { mean: ci.meanDiff, ci95: { lo: ci.lo, hi: ci.hi } },
      ece: eceVal,
      forecastFailedRate,
      ingestRejectRate,
      incompleteHorizonQuestions,
      brierByHorizon,
      calibration: bins
    };
  if (cacheHitRate !== undefined) metrics.cacheHitRate = cacheHitRate;

  const compositionMeta = meta["composition_annotations"]
    ? (JSON.parse(meta["composition_annotations"]) as Record<string, unknown>)
    : null;

  let selection: Report["selection"];
  if (sampleMeta) {
    const universe: NonNullable<Report["selection"]>["universe"] = {
      mode: String(universeMeta?.mode ?? evalFrozen.protocol.universe.mode)
    };
    const ingestAsOf = String(universeMeta?.ingestAsOf ?? evalFrozen.protocol.universe.ingestAsOf);
    if (ingestAsOf) universe.ingestAsOf = ingestAsOf;
    if (universeMeta?.paginationMode) universe.paginationMode = String(universeMeta.paginationMode);
    if (typeof universeMeta?.pagesFetched === "number") universe.pagesFetched = universeMeta.pagesFetched;
    if (typeof universeMeta?.fetchedUnique === "number") universe.fetchedUnique = universeMeta.fetchedUnique;
    if (typeof universeMeta?.universeAfterFilters === "number")
      universe.universeAfterFilters = universeMeta.universeAfterFilters;
    if (typeof sampleMeta.intersectionEligible === "number")
      universe.intersectionEligible = sampleMeta.intersectionEligible;

    selection = {
      universe,
      sampling: {
        seed: Number(sampleMeta.seed),
        targetQuestions: Number(sampleMeta.targetQuestions),
        selectedQuestions: Number(sampleMeta.selectedQuestions),
        expectedHeldoutQuestions: Number(sampleMeta.expectedHeldoutQuestions),
        strataRule: "resolutionQuarter+category proportional",
        stratumCounts: (sampleMeta.stratumCounts as Record<string, number>) ?? {},
        modelIdsIntersection: (sampleMeta.modelIdsUsed as string[]) ?? modelsCfg.models.map((m) => m.id),
        eligibleByModel: (sampleMeta.eligibleByModel as Record<string, number>) ?? {}
      },
      temporalSplit: {
        heldoutPct: evalFrozen.protocol.temporalSplit.heldoutLastPctByResolutionDate,
        heldoutQuestionsN,
        trainQuestionsN
      },
      ...(compositionMeta ? { composition: compositionMeta } : {})
    };
  }

  const report: Report = {
    runId,
    verdict,
    reason,
    metrics,
    integrity: {
      hardIntegrityFailure,
      auditRequired,
      auditTriggers,
      leakageSuspected,
      canaryBrierByModel,
      canaryScoredN,
      ...(temporalCanary ? { temporalCanary } : {}),
      configHash: evalFrozen.freezeHash,
      mixedModels,
      pipelineModelIds: [...pipelineModelIds]
    }
  };
  if (selection) report.selection = selection;

  // write output
  const outDir = path.join(process.cwd(), "output", report.runId);
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(report, null, 2) + "\n", "utf-8");
  fs.writeFileSync(
    path.join(outDir, "report.md"),
    `# Report\n\n## Integrity (read first)\n\n- auditRequired: **${auditRequired}**\n- auditTriggers: ${auditTriggers.length ? auditTriggers.join(", ") : "none"}\n- hardIntegrityFailure: **${hardIntegrityFailure}**\n\n## Verdict\n\n**${report.verdict}**${reason ? ` (${reason})` : ""}\n`,
    "utf-8"
  );

  return report;
}

