import { describe, expect, test } from "vitest";
import { computeSnapshotAtOrBefore } from "../../src/ingest/store.js";

describe("computeSnapshotAtOrBefore", () => {
  test("picks the latest point at or before snapshot", () => {
    const hist = [
      { ts: "2026-01-01T00:00:00.000Z", mid: 0.4 },
      { ts: "2026-01-02T00:00:00.000Z", mid: 0.5 },
      { ts: "2026-01-03T00:00:00.000Z", mid: 0.6 }
    ];
    const p = computeSnapshotAtOrBefore(hist, "2026-01-02T12:00:00.000Z");
    expect(p).toEqual({ ts: "2026-01-02T00:00:00.000Z", mid: 0.5 });
  });

  test("returns null if no point before snapshot", () => {
    const hist = [{ ts: "2026-01-03T00:00:00.000Z", mid: 0.6 }];
    const p = computeSnapshotAtOrBefore(hist, "2026-01-02T12:00:00.000Z");
    expect(p).toBeNull();
  });
});

