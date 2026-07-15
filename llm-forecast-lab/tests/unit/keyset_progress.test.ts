import { describe, expect, test } from "vitest";
import { monthChunks, readKeysetProgress } from "../../src/ingest/gamma_keyset_ingest.js";
import { openDb } from "../../src/db.js";

describe("readKeysetProgress", () => {
  test("complete keyset is 100%", () => {
    const db = openDb("fixtures");
    db.prepare("insert into meta(k,v) values('gamma_keyset_complete','true') on conflict(k) do update set v=excluded.v").run();
    const chunks = monthChunks("2024-01-01", "2026-12-31");
    db.prepare(
      "insert into meta(k,v) values('gamma_keyset_chunks_done',@v) on conflict(k) do update set v=excluded.v"
    ).run({ v: JSON.stringify(chunks.map((c) => c.id)) });
    const p = readKeysetProgress(db, "2024-01-01", "2026-12-31");
    expect(p.keysetPct).toBe(100);
    expect(p.complete).toBe(true);
  });

  test("intra-chunk pct rises as pages advance", () => {
    const db = openDb("fixtures");
    db.prepare("delete from meta where k = 'gamma_keyset_complete'").run();
    db.prepare(
      "insert into meta(k,v) values('gamma_keyset_chunks_done',@v) on conflict(k) do update set v=excluded.v"
    ).run({ v: JSON.stringify(["2024-01", "2024-02"]) });
    db.prepare("insert into meta(k,v) values('gamma_keyset_chunk_pages_est_2024-01','400') on conflict(k) do update set v=excluded.v").run();
    db.prepare("insert into meta(k,v) values('gamma_keyset_chunk_pages_est_2024-02','600') on conflict(k) do update set v=excluded.v").run();
    db.prepare("insert into meta(k,v) values('gamma_keyset_active_chunk','2024-03') on conflict(k) do update set v=excluded.v").run();
    db.prepare("insert into meta(k,v) values('gamma_keyset_chunk_pages_est_2024-03','500') on conflict(k) do update set v=excluded.v").run();
    db.prepare("insert into meta(k,v) values('gamma_keyset_active_chunk_pages','100') on conflict(k) do update set v=excluded.v").run();
    const early = readKeysetProgress(db, "2024-01-01", "2026-12-31");
    db.prepare("insert into meta(k,v) values('gamma_keyset_active_chunk_pages','300') on conflict(k) do update set v=excluded.v").run();
    const later = readKeysetProgress(db, "2024-01-01", "2026-12-31");
    expect(later.keysetPct).toBeGreaterThan(early.keysetPct);
    expect(early.keysetPct).toBeLessThan(99.9);
  });
});
