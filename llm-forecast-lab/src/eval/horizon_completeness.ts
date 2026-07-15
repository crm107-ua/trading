import type Database from "better-sqlite3";

export function horizonCompleteQuestionIds(
  db: Database.Database,
  questionIds: Iterable<string>,
  horizonsHours: number[]
): { complete: Set<string>; incomplete: string[] } {
  const complete = new Set<string>();
  const incomplete: string[] = [];
  const placeholders = horizonsHours.map(() => "?").join(",");
  const stmt = db.prepare(
    `
    select count(distinct horizon_hours) as n
    from market_snapshots
    where question_id = ?
      and horizon_hours in (${placeholders})
  `
  );

  for (const questionId of questionIds) {
    const row = stmt.get(questionId, ...horizonsHours) as { n: number };
    if (row.n === horizonsHours.length) complete.add(questionId);
    else incomplete.push(questionId);
  }

  return { complete, incomplete };
}
