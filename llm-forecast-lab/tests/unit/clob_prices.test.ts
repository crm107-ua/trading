import { describe, expect, test, vi, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fetchPriceHistoryCached, readClobCache, writeClobCache } from "../../src/ingest/clob_prices.js";

describe("clob price cache", () => {
  const tokenId = "test_token_empty_cache";
  const cachePath = path.join(process.cwd(), "data", "clob", "test_token_empty_cache.json");

  afterEach(() => {
    if (fs.existsSync(cachePath)) fs.unlinkSync(cachePath);
    vi.restoreAllMocks();
  });

  test("empty cache file is treated as miss", async () => {
    writeClobCache(tokenId, []);
    expect(readClobCache(tokenId)).toEqual([]);

    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ history: [{ t: 1_700_000_000, p: 0.42 }] })
    } as Response);

    const { points, cacheHit } = await fetchPriceHistoryCached(tokenId, {
      startIso: "2023-09-01T00:00:00Z",
      endIso: "2023-09-10T00:00:00Z"
    });

    expect(cacheHit).toBe(false);
    expect(points.length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalled();
  });
});
