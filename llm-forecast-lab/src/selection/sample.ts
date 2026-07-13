import type Database from "better-sqlite3";
import type { EvalFrozen } from "../config.js";
import type { ModelsConfig } from "../config.js";
import { isEligibleForModel } from "../integrity/leakage.js";
import { mulberry32 } from "../eval/bootstrap.js";

export type QuestionRow = {
  id: string;
  category: string | null;
  resolution_date: string;
  liquidity_proxy: number;
};

export type SampleReport = {
  seed: number;
  targetQuestions: number;
  selectedQuestions: number;
  expectedHeldoutQuestions: number;
  universeAfterFilters: number;
  intersectionEligible: number;
  eligibleByModel: Record<string, number>;
  stratumCounts: Record<string, number>;
  modelIdsUsed: string[];
};

export function resolutionQuarter(iso: string): string {
  const d = new Date(iso);
  const y = d.getUTCFullYear();
  const q = Math.floor(d.getUTCMonth() / 3) + 1;
  return `${y}-Q${q}`;
}

export function stratumKey(q: QuestionRow, cfg: EvalFrozen["protocol"]["runSampling"]): string {
  const parts: string[] = [];
  if (cfg.strata.resolutionQuarter.enabled) parts.push(resolutionQuarter(q.resolution_date));
  if (cfg.strata.category.enabled) {
    parts.push(q.category?.trim() || cfg.strata.category.unknownBucket);
  }
  return parts.join("|") || "ALL";
}

export function intersectionEligibleQuestions(
  questions: QuestionRow[],
  modelsCfg: ModelsConfig,
  evalFrozen: EvalFrozen
): { eligible: QuestionRow[]; eligibleByModel: Record<string, number> } {
  const eligibleByModel: Record<string, number> = {};
  const sets = modelsCfg.models.map((model) => {
    const ids = new Set<string>();
    for (const q of questions) {
      const el = isEligibleForModel({
        resolutionDateIso: q.resolution_date,
        modelTrainingCutoff: model.trainingCutoff,
        safetyMarginDays: evalFrozen.protocol.integrity.safetyMarginDays
      });
      if (el.eligible) ids.add(q.id);
    }
    eligibleByModel[model.id] = ids.size;
    return ids;
  });

  let intersection = new Set(questions.map((q) => q.id));
  for (const s of sets) {
    intersection = new Set([...intersection].filter((id) => s.has(id)));
  }

  const eligible = questions.filter((q) => intersection.has(q.id));
  return { eligible, eligibleByModel };
}

export function stratifiedSelect(args: {
  pool: QuestionRow[];
  target: number;
  seed: number;
  strataCfg: EvalFrozen["protocol"]["runSampling"];
}): { selected: QuestionRow[]; stratumCounts: Record<string, number> } {
  const rng = mulberry32(args.seed);
  const byStratum = new Map<string, QuestionRow[]>();
  for (const q of args.pool) {
    const k = stratumKey(q, args.strataCfg);
    const arr = byStratum.get(k) ?? [];
    arr.push(q);
    byStratum.set(k, arr);
  }

  const strata = [...byStratum.entries()];
  const total = args.pool.length;
  const target = Math.min(args.target, total);
  const allocations = new Map<string, number>();

  if (total === 0) return { selected: [], stratumCounts: {} };

  let assigned = 0;
  for (const [k, rows] of strata) {
    const prop = args.strataCfg.strata.resolutionQuarter.proportional || args.strataCfg.strata.category.proportional;
    const n = prop ? Math.floor((rows.length / total) * target) : Math.ceil(target / strata.length);
    allocations.set(k, Math.min(rows.length, n));
    assigned += allocations.get(k) ?? 0;
  }

  // Fill remainder by largest strata first (deterministic order by key).
  const sortedKeys = strata.map(([k]) => k).sort();
  let i = 0;
  while (assigned < target) {
    const k = sortedKeys[i % sortedKeys.length]!;
    const cap = (byStratum.get(k) ?? []).length;
    const cur = allocations.get(k) ?? 0;
    if (cur < cap) {
      allocations.set(k, cur + 1);
      assigned += 1;
    }
    i += 1;
    if (i > target * strata.length * 2) break;
  }

  const selected: QuestionRow[] = [];
  const stratumCounts: Record<string, number> = {};
  for (const k of sortedKeys) {
    const rows = [...(byStratum.get(k) ?? [])];
    rows.sort((a, b) => a.id.localeCompare(b.id));
    for (let j = rows.length - 1; j > 0; j--) {
      const r = rng();
      const swap = Math.floor(r * (j + 1));
      const tmp = rows[j]!;
      rows[j] = rows[swap]!;
      rows[swap] = tmp;
    }
    const take = allocations.get(k) ?? 0;
    const picked = rows.slice(0, take);
    stratumCounts[k] = picked.length;
    selected.push(...picked);
  }

  selected.sort((a, b) => Date.parse(a.resolution_date) - Date.parse(b.resolution_date));
  return { selected: selected.slice(0, target), stratumCounts };
}

export function computeSampleReport(args: {
  questions: QuestionRow[];
  evalFrozen: EvalFrozen;
  modelsCfg: ModelsConfig;
}): SampleReport {
  const cfg = args.evalFrozen.protocol.runSampling;
  const { eligible, eligibleByModel } = intersectionEligibleQuestions(
    args.questions,
    args.modelsCfg,
    args.evalFrozen
  );

  let target = cfg.targetQuestions;
  const heldoutPct = args.evalFrozen.protocol.temporalSplit.heldoutLastPctByResolutionDate;
  while (target > eligible.length && target > 0) target -= 1;
  while (Math.floor(target * heldoutPct) < cfg.minHeldoutQuestionsAfterSplit && target < eligible.length) {
    target += 1;
  }
  target = Math.min(target, eligible.length);

  const { selected, stratumCounts } = stratifiedSelect({
    pool: eligible,
    target,
    seed: cfg.seed,
    strataCfg: cfg
  });

  return {
    seed: cfg.seed,
    targetQuestions: cfg.targetQuestions,
    selectedQuestions: selected.length,
    expectedHeldoutQuestions: Math.floor(selected.length * heldoutPct),
    universeAfterFilters: args.questions.length,
    intersectionEligible: eligible.length,
    eligibleByModel,
    stratumCounts,
    modelIdsUsed: args.modelsCfg.models.map((m) => m.id)
  };
}

export function persistRunSample(db: Database.Database, selected: QuestionRow[], cfg: EvalFrozen): void {
  db.prepare("delete from run_questions").run();
  const ins = db.prepare(`
    insert into run_questions (question_id, stratum_key, sort_key)
    values (@question_id, @stratum_key, @sort_key)
  `);
  const tx = db.transaction((rows: QuestionRow[]) => {
    let i = 0;
    for (const q of rows) {
      ins.run({
        question_id: q.id,
        stratum_key: stratumKey(q, cfg.protocol.runSampling),
        sort_key: i++
      });
    }
  });
  tx(selected);
}

export function applyRunSampling(
  db: Database.Database,
  evalFrozen: EvalFrozen,
  modelsCfg: ModelsConfig
): SampleReport {
  const rows = db
    .prepare(
      `select id, category, resolution_date, liquidity_proxy from questions order by resolution_date asc`
    )
    .all() as QuestionRow[];

  const report = computeSampleReport({ questions: rows, evalFrozen, modelsCfg });
  if (!evalFrozen.protocol.runSampling.enabled) return report;

  const { eligible } = intersectionEligibleQuestions(rows, modelsCfg, evalFrozen);
  const { selected } = stratifiedSelect({
    pool: eligible,
    target: report.selectedQuestions,
    seed: evalFrozen.protocol.runSampling.seed,
    strataCfg: evalFrozen.protocol.runSampling
  });
  persistRunSample(db, selected, evalFrozen);
  return report;
}
