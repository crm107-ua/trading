import type Database from "better-sqlite3";
import { generateReport, type Report } from "./report.js";
import { scoreForecasts } from "./score_run.js";

export type EvalDayDResult = {
  score: ReturnType<typeof scoreForecasts>;
  report: Report;
  outputDir: string;
};

/** Day D bundle: score → report only. Sim-paper/grid are separate, post-verdict, pre-reg required. */
export function runEvalDayD(
  db: Database.Database,
  args: { pipeline: string; mode: "fixtures" | "live" }
): EvalDayDResult {
  const score = scoreForecasts(db);
  const report = generateReport(db, { pipeline: args.pipeline, mode: args.mode });
  const outputDir = `${process.cwd()}/output/${report.runId}`;
  return { score, report, outputDir };
}
