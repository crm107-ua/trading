import fs from "node:fs";
import path from "node:path";
import { computeFreezeHash, EvalFrozenSchema } from "./config.js";

/**
 * One-time helper: compute and write freezeHash into config/eval_frozen.json.
 * This is NOT used by the main runtime. It's a deliberate, explicit action.
 */
export function freezeEvalConfig(configDir: string): { freezeHash: string } {
  const p = path.join(configDir, "eval_frozen.json");
  const raw = fs.readFileSync(p, "utf-8");
  const parsed = EvalFrozenSchema.parse(JSON.parse(raw));
  const freezeHash = computeFreezeHash(parsed);
  const next = { ...parsed, freezeHash };
  fs.writeFileSync(p, JSON.stringify(next, null, 2) + "\n", "utf-8");
  return { freezeHash };
}

