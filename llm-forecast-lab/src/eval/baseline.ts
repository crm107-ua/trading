import type Database from "better-sqlite3";

export type BaselineRow = {
  questionId: string;
  horizonHours: number;
  forecastTs: string;
  p: number;
  y: 0 | 1;
};

export function marketBaselineRows(db: Database.Database): BaselineRow[] {
  const rows = db
    .prepare(
      `
      select q.id as question_id, ms.horizon_hours, ms.snapshot_ts, ms.market_mid, q.resolved_outcome
      from questions q
      join market_snapshots ms on ms.question_id = q.id
    `
    )
    .all() as Array<{
    question_id: string;
    horizon_hours: number;
    snapshot_ts: string;
    market_mid: number;
    resolved_outcome: 0 | 1;
  }>;

  return rows.map((r) => ({
    questionId: r.question_id,
    horizonHours: r.horizon_hours,
    forecastTs: r.snapshot_ts,
    p: r.market_mid,
    y: r.resolved_outcome
  }));
}

