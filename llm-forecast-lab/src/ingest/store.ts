import crypto from "node:crypto";
import type Database from "better-sqlite3";
import { Question } from "./types.js";

export type IngestStats = {
  ingested: number;
  rejects: number;
};

export function stableId(input: string): string {
  return crypto.createHash("sha256").update(input).digest("hex").slice(0, 24);
}

export function upsertQuestions(
  db: Database.Database,
  questions: Question[],
  opts?: { canaryOnly?: boolean }
): IngestStats {
  const canaryOnly = opts?.canaryOnly ? 1 : 0;
  const insQ = db.prepare(`
    insert into questions (id, source, question_text, description, category, resolution_date, resolved_outcome, ambiguous_resolution, liquidity_proxy, canary_only)
    values (@id, @source, @question_text, @description, @category, @resolution_date, @resolved_outcome, @ambiguous_resolution, @liquidity_proxy, @canary_only)
    on conflict(id) do update set
      question_text=excluded.question_text,
      description=excluded.description,
      category=excluded.category,
      resolution_date=excluded.resolution_date,
      resolved_outcome=excluded.resolved_outcome,
      ambiguous_resolution=excluded.ambiguous_resolution,
      liquidity_proxy=excluded.liquidity_proxy,
      canary_only=excluded.canary_only
  `);

  const tx = db.transaction((rows: Question[]) => {
    for (const q of rows) {
      insQ.run({
        id: q.id,
        source: q.source,
        question_text: q.questionText,
        description: q.description ?? null,
        category: q.category ?? null,
        resolution_date: q.resolution.resolutionDate,
        resolved_outcome: q.resolution.resolvedOutcome === "YES" ? 1 : 0,
        ambiguous_resolution: q.ambiguousResolution ? 1 : 0,
        liquidity_proxy: q.liquidityProxy,
        canary_only: canaryOnly
      });
    }
  });
  tx(questions);
  return { ingested: questions.length, rejects: 0 };
}

export function computeSnapshotAtOrBefore(
  history: { ts: string; mid: number }[],
  snapshotIso: string
): { ts: string; mid: number } | null {
  const snap = Date.parse(snapshotIso);
  if (!Number.isFinite(snap)) return null;
  let best: { ts: string; mid: number } | null = null;
  for (const p of history) {
    const t = Date.parse(p.ts);
    if (!Number.isFinite(t)) continue;
    if (t <= snap) {
      if (!best) best = p;
      else if (Date.parse(best.ts) < t) best = p;
    }
  }
  return best;
}

export function upsertMarketSnapshots(
  db: Database.Database,
  question: Question,
  horizonsHours: number[]
): { inserted: number; rejects: number } {
  const ins = db.prepare(`
    insert into market_snapshots (question_id, horizon_hours, snapshot_ts, market_mid)
    values (@question_id, @horizon_hours, @snapshot_ts, @market_mid)
    on conflict(question_id, horizon_hours) do update set
      snapshot_ts=excluded.snapshot_ts,
      market_mid=excluded.market_mid
  `);

  let inserted = 0;
  let rejects = 0;
  for (const h of horizonsHours) {
    const resTs = Date.parse(question.resolution.resolutionDate);
    const snapTs = new Date(resTs - h * 3600 * 1000).toISOString();
    const point = computeSnapshotAtOrBefore(question.priceHistory, snapTs);
    if (!point) {
      rejects += 1;
      continue;
    }
    ins.run({
      question_id: question.id,
      horizon_hours: h,
      snapshot_ts: point.ts,
      market_mid: point.mid
    });
    inserted += 1;
  }
  return { inserted, rejects };
}

