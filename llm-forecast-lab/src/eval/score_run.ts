import type Database from "better-sqlite3";
import { loadEvalFrozen } from "../config.js";
import { horizonCompleteQuestionIds } from "./horizon_completeness.js";
import { brier, logLoss } from "./scoring.js";

export function scoreForecasts(db: Database.Database): {
  scored: number;
  skippedFailed: number;
  skippedIncompleteHorizon: number;
} {
  const evalFrozen = loadEvalFrozen("./config");
  const horizons = evalFrozen.protocol.horizonsHoursBeforeResolution;
  const forecastQuestionIds = (
    db.prepare("select distinct question_id from forecasts").all() as Array<{ question_id: string }>
  ).map((r) => r.question_id);
  const { complete: horizonComplete } = horizonCompleteQuestionIds(db, forecastQuestionIds, horizons);

  const rows = db
    .prepare(
      `
      select f.id as forecast_id, f.question_id, f.p, f.forecast_failed, q.resolved_outcome
      from forecasts f
      join questions q on q.id = f.question_id
    `
    )
    .all() as Array<{
    forecast_id: string;
    question_id: string;
    p: number | null;
    forecast_failed: 0 | 1;
    resolved_outcome: 0 | 1;
  }>;

  const ins = db.prepare(`
    insert into scores (forecast_id, y, brier, log_loss)
    values (@forecast_id, @y, @brier, @log_loss)
    on conflict(forecast_id) do update set
      y=excluded.y,
      brier=excluded.brier,
      log_loss=excluded.log_loss
  `);

  let scored = 0;
  let skippedFailed = 0;
  let skippedIncompleteHorizon = 0;
  const tx = db.transaction(() => {
    for (const r of rows) {
      if (!horizonComplete.has(r.question_id)) {
        skippedIncompleteHorizon += 1;
        continue;
      }
      if (r.forecast_failed || r.p === null) {
        skippedFailed += 1;
        continue;
      }
      const y = r.resolved_outcome as 0 | 1;
      ins.run({
        forecast_id: r.forecast_id,
        y,
        brier: brier(r.p, y),
        log_loss: logLoss(r.p, y)
      });
      scored += 1;
    }
  });
  tx();

  return { scored, skippedFailed, skippedIncompleteHorizon };
}

