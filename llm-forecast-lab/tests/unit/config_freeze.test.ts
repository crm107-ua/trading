import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { computeFreezeHash, EvalFrozenSchema } from "../../src/config.js";

function readEvalFixture(): unknown {
  const p = path.join(process.cwd(), "config", "eval_frozen.json");
  return JSON.parse(fs.readFileSync(p, "utf-8")) as unknown;
}

describe("eval_frozen freezeHash", () => {
  test("computeFreezeHash is stable and excludes freezeHash field", () => {
    const data = EvalFrozenSchema.parse(readEvalFixture());
    const h1 = computeFreezeHash(data);
    const h2 = computeFreezeHash({ ...data, freezeHash: "something_else" });
    expect(h1).toEqual(h2);
    expect(h1).toMatch(/^[0-9a-f]{64}$/);
  });
});

