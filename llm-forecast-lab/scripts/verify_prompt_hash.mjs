import fs from "node:fs";
import { openDb } from "../dist/db.js";
import { hashPrompt } from "../dist/pipeline/cache.js";

const tpl = fs.readFileSync("src/pipeline/forecasters/prompts/naive.txt", "utf-8");
const oldTpl = tpl.replace(
  /Output format[\s\S]*?Example shape:\n\{[^\n]+\}\n\n/,
  "Return ONLY JSON with keys:\n  p (number 0..1),\n  key_factors (string[]),\n  base_rate_considered (string),\n  confidence_note (string).\n\n"
);

const db = openDb("live");
const rows = db
  .prepare(
    `
  select f.prompt_hash, q.question_text, q.description, ms.snapshot_ts, ms.market_mid
  from forecasts f
  join questions q on q.id = f.question_id
  join market_snapshots ms on ms.question_id = f.question_id and ms.horizon_hours = f.horizon_hours
`
  )
  .all();

function fill(t, r) {
  return t
    .replaceAll("{{QUESTION_TEXT}}", r.question_text)
    .replaceAll("{{DESCRIPTION}}", r.description ?? "")
    .replaceAll("{{SNAPSHOT_TS}}", r.snapshot_ts)
    .replaceAll("{{MARKET_MID}}", String(r.market_mid));
}

let matchNew = 0;
let matchOld = 0;
let mismatch = 0;
for (const r of rows) {
  const nh = hashPrompt(fill(tpl, r));
  const oh = hashPrompt(fill(oldTpl, r));
  if (r.prompt_hash === nh) matchNew += 1;
  else if (r.prompt_hash === oh) matchOld += 1;
  else mismatch += 1;
}

console.log(JSON.stringify({ total: rows.length, matchNewTpl: matchNew, matchOldTpl: matchOld, mismatch }, null, 2));
