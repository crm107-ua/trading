import { describe, expect, test } from "vitest";
import { hashPrompt } from "../../src/pipeline/cache.js";

describe("prompt hashing", () => {
  test("hashPrompt is stable", () => {
    expect(hashPrompt("abc")).toEqual(hashPrompt("abc"));
    expect(hashPrompt("abc")).not.toEqual(hashPrompt("abcd"));
    expect(hashPrompt("abc")).toMatch(/^[0-9a-f]{64}$/);
  });
});

