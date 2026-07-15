import fs from "node:fs";
import path from "node:path";
import type Database from "better-sqlite3";
import { z } from "zod";
import { loadEvalFrozen } from "../config.js";
import { horizonCompleteQuestionIds } from "./horizon_completeness.js";

const SimPaperConfigSchema = z.object({
  verdictBinding: z.literal(false),
  hypothesis: z.string(),
  sizeShares: z.number().positive(),
  minNetEdge: z.number().nonnegative(),
  takerFee: z.number().nonnegative(),
  safetyBuffer: z.number().nonnegative(),
  slippagePer100Shares: z.number().nonnegative(),
  horizonsHours: z.array(z.number().int().positive()),
  maxTradesPerQuestion: z.number().int().positive(),
  preferHorizonHours: z.number().int().positive(),
  initialCapitalUsdc: z.number().positive(),
  requireCompleteHorizons: z.boolean()
});
export type SimPaperConfig = z.infer<typeof SimPaperConfigSchema>;

export type SimPaperReport = {
  verdictBinding: false;
  hypothesis: string;
  config: SimPaperConfig;
  sample: {
    heldoutQuestionsTotal: number;
    completeHorizonQuestions: number;
    incompleteHorizonQuestions: number;
    tradedQuestions: number;
    skippedNoEdge: number;
    skippedIncomplete: number;
  };
  trades: Array<{
    questionId: string;
    horizonHours: number;
    side: "YES" | "NO";
    entry: number;
    modelP: number;
    marketMid: number;
    netEdge: number;
    frictionPerShare: number;
    resolvedOutcome: 0 | 1;
    pnlUsdc: number;
  }>;
  summary: {
    initialCapitalUsdc: number;
    endingCapitalUsdc: number;
    netPnlUsdc: number;
    returnPct: number;
    trades: number;
    wins: number;
    winRate: number;
    avgPnlPerTradeUsdc: number;
    totalFrictionUsdc: number;
  };
  calibrationNote: string;
};

export function loadSimPaperConfig(configDir = "./config"): SimPaperConfig {
  const p = path.join(configDir, "sim_paper.json");
  return SimPaperConfigSchema.parse(JSON.parse(fs.readFileSync(p, "utf-8")));
}

function frictionPerShare(entry: number, cfg: SimPaperConfig): number {
  return (
    cfg.takerFee * entry +
    cfg.safetyBuffer +
    cfg.slippagePer100Shares * (cfg.sizeShares / 100)
  );
}

export function runSimPaper(
  db: Database.Database,
  args: { pipeline: string; cfg?: SimPaperConfig }
): SimPaperReport {
  const evalFrozen = loadEvalFrozen("./config");
  const cfg = args.cfg ?? loadSimPaperConfig("./config");
  const horizons = new Set(cfg.horizonsHours);

  const sampleQIds = (
    db.prepare("select question_id from run_questions").all() as Array<{ question_id: string }>
  ).map((r) => r.question_id);
  const { complete, incomplete } = horizonCompleteQuestionIds(db, sampleQIds, cfg.horizonsHours);

  const rows = db
    .prepare(
      `
      select f.question_id, f.horizon_hours, f.p, f.forecast_failed,
             q.resolution_date, q.resolved_outcome, ms.market_mid
      from forecasts f
      join questions q on q.id = f.question_id
      join market_snapshots ms on ms.question_id = f.question_id and ms.horizon_hours = f.horizon_hours
      where f.pipeline = @pipeline and q.canary_only = 0
        and f.question_id in (select question_id from run_questions)
      order by q.resolution_date asc
    `
    )
    .all({ pipeline: args.pipeline }) as Array<{
    question_id: string;
    horizon_hours: number;
    p: number | null;
    forecast_failed: 0 | 1;
    resolution_date: string;
    resolved_outcome: 0 | 1;
    market_mid: number;
  }>;

  const byQ = new Map<string, typeof rows>();
  for (const r of rows) {
    const cur = byQ.get(r.question_id) ?? [];
    cur.push(r);
    byQ.set(r.question_id, cur);
  }

  const qIdsSorted = [...byQ.keys()].sort(
    (a, b) =>
      Date.parse(byQ.get(a)![0]!.resolution_date) - Date.parse(byQ.get(b)![0]!.resolution_date)
  );
  const heldoutStartQ = Math.floor(
    (1 - evalFrozen.protocol.temporalSplit.heldoutLastPctByResolutionDate) * qIdsSorted.length
  );
  const heldoutQIds = qIdsSorted.slice(heldoutStartQ);

  const trades: SimPaperReport["trades"] = [];
  let skippedNoEdge = 0;
  let skippedIncomplete = 0;

  for (const qid of heldoutQIds) {
    if (cfg.requireCompleteHorizons && !complete.has(qid)) {
      skippedIncomplete += 1;
      continue;
    }
    const qrows = (byQ.get(qid) ?? []).filter((r) => horizons.has(r.horizon_hours));
    const candidates = qrows
      .filter((r) => !r.forecast_failed && r.p !== null)
      .sort((a, b) => {
        if (a.horizon_hours === cfg.preferHorizonHours) return -1;
        if (b.horizon_hours === cfg.preferHorizonHours) return 1;
        return b.horizon_hours - a.horizon_hours;
      });

    let placed = 0;
    for (const r of candidates) {
      if (placed >= cfg.maxTradesPerQuestion) break;
      const p = r.p as number;
      const mid = r.market_mid;
      const y = r.resolved_outcome;

      const fr = frictionPerShare(mid, cfg);
      const yesNet = p - mid - fr;
      const noNet = mid - p - fr;

      if (yesNet >= cfg.minNetEdge) {
        trades.push({
          questionId: qid,
          horizonHours: r.horizon_hours,
          side: "YES",
          entry: mid,
          modelP: p,
          marketMid: mid,
          netEdge: yesNet,
          frictionPerShare: fr,
          resolvedOutcome: y,
          pnlUsdc: cfg.sizeShares * (y - mid) - fr * cfg.sizeShares
        });
        placed += 1;
        continue;
      }
      if (noNet >= cfg.minNetEdge) {
        trades.push({
          questionId: qid,
          horizonHours: r.horizon_hours,
          side: "NO",
          entry: 1 - mid,
          modelP: p,
          marketMid: mid,
          netEdge: noNet,
          frictionPerShare: fr,
          resolvedOutcome: y,
          pnlUsdc: cfg.sizeShares * (mid - y) - fr * cfg.sizeShares
        });
        placed += 1;
      }
    }
    if (placed === 0 && complete.has(qid)) skippedNoEdge += 1;
  }

  const netPnl = trades.reduce((s, t) => s + t.pnlUsdc, 0);
  const friction = trades.reduce((s, t) => s + t.frictionPerShare * cfg.sizeShares, 0);
  const wins = trades.filter((t) => t.pnlUsdc > 0).length;

  return {
    verdictBinding: false,
    hypothesis: cfg.hypothesis,
    config: cfg,
    sample: {
      heldoutQuestionsTotal: heldoutQIds.length,
      completeHorizonQuestions: heldoutQIds.filter((id) => complete.has(id)).length,
      incompleteHorizonQuestions: incomplete.filter((id) => heldoutQIds.includes(id)).length,
      tradedQuestions: new Set(trades.map((t) => t.questionId)).size,
      skippedNoEdge,
      skippedIncomplete
    },
    trades,
    summary: {
      initialCapitalUsdc: cfg.initialCapitalUsdc,
      endingCapitalUsdc: cfg.initialCapitalUsdc + netPnl,
      netPnlUsdc: netPnl,
      returnPct: (netPnl / cfg.initialCapitalUsdc) * 100,
      trades: trades.length,
      wins,
      winRate: trades.length === 0 ? 0 : wins / trades.length,
      avgPnlPerTradeUsdc: trades.length === 0 ? 0 : netPnl / trades.length,
      totalFrictionUsdc: friction
    },
    calibrationNote:
      "Exploratory mid-only taker sim on held-out sample. Tune config/sim_paper.json (minNetEdge, horizons, sizeShares). Not binding; skill Brier from report remains primary."
  };
}
