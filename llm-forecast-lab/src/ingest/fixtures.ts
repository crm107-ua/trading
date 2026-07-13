import fs from "node:fs";
import path from "node:path";
import { Question, QuestionSchema } from "./types.js";

export function loadFixtureQuestions(): Question[] {
  const p = path.join(process.cwd(), "tests", "golden", "fixtures", "questions.json");
  const raw = JSON.parse(fs.readFileSync(p, "utf-8")) as unknown;
  const arr = Array.isArray(raw) ? raw : [];
  const out: Question[] = [];
  for (const item of arr) out.push(QuestionSchema.parse(item));
  return out;
}

