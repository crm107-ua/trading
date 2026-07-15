import fs from "node:fs";
import path from "node:path";
import { hashPrompt } from "../../cache.js";

export function promptHashForNim(args: {
  questionId: string;
  questionText: string;
  description: string | null;
  snapshotTs: string;
  marketMid: number;
}): string {
  const tpl = fs.readFileSync(
    path.join(process.cwd(), "src", "pipeline", "forecasters", "prompts", "naive.txt"),
    "utf-8"
  );
  const filled = tpl
    .replaceAll("{{QUESTION_TEXT}}", args.questionText)
    .replaceAll("{{DESCRIPTION}}", args.description ?? "")
    .replaceAll("{{SNAPSHOT_TS}}", args.snapshotTs)
    .replaceAll("{{MARKET_MID}}", String(args.marketMid));
  return hashPrompt(filled);
}
