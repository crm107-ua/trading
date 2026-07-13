import { describe, expect, test } from "vitest";
import { computeSlugHeuristics, slugHeuristicPatterns } from "../../src/ingest/composition_notes.js";

describe("composition_notes", () => {
  test("sports regex catches league slug matriculas", () => {
    const items = [
      {
        slug: "lal-mad-elc-2025-08-23-mad",
        question: "Will Atletico Madrid win on 2025-08-23?",
        resolution_date: "2025-08-23T17:30:00Z"
      },
      {
        slug: "tur-kon-bes-2025-10-22-bes",
        question: "Will Beşiktaş JK win on 2025-10-22?",
        resolution_date: "2025-10-22T17:00:00Z"
      }
    ];
    const rep = computeSlugHeuristics(items);
    expect(rep.counts.sports?.n).toBe(2);
  });

  test("patterns include league prefixes", () => {
    const sports = slugHeuristicPatterns().find((p) => p.name === "sports");
    expect(sports?.re.test("lal-bet-bil-2025-08-31-bet")).toBe(true);
    expect(sports?.re.test("fl1-aja-lyo-2025-11-23-lyo")).toBe(true);
  });
});
