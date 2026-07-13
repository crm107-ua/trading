import fs from "node:fs";
import path from "node:path";
import { z } from "zod";
import type { PricePoint } from "./types.js";

const CLOB_BASE_URL = "https://clob.polymarket.com";

const ClobHistoryResponse = z.object({
  history: z
    .array(
      z.object({
        t: z.number(),
        p: z.number()
      })
    )
    .optional()
});

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function clobCacheDir(): string {
  return path.resolve(process.cwd(), "data", "clob");
}

function clobCachePath(tokenId: string): string {
  const safe = tokenId.replace(/[^a-zA-Z0-9_-]/g, "_");
  return path.join(clobCacheDir(), `${safe}.json`);
}

export function readClobCache(tokenId: string): PricePoint[] | null {
  const p = clobCachePath(tokenId);
  if (!fs.existsSync(p)) return null;
  try {
    const raw = JSON.parse(fs.readFileSync(p, "utf-8")) as unknown;
    return z.array(z.object({ ts: z.string(), mid: z.number() })).parse(raw);
  } catch {
    return null;
  }
}

export function writeClobCache(tokenId: string, points: PricePoint[]): void {
  fs.mkdirSync(clobCacheDir(), { recursive: true });
  fs.writeFileSync(clobCachePath(tokenId), JSON.stringify(points, null, 2) + "\n", "utf-8");
}

export async function fetchPriceHistoryCached(tokenId: string): Promise<{
  points: PricePoint[];
  cacheHit: boolean;
}> {
  const cached = readClobCache(tokenId);
  if (cached) return { points: cached, cacheHit: true };

  const url =
    `${CLOB_BASE_URL}/prices-history?market=${encodeURIComponent(tokenId)}` +
    `&interval=1d&fidelity=60`;

  for (let attempt = 0; attempt < 8; attempt++) {
    const res = await fetch(url);
    if (res.status === 429 || res.status === 403) {
      await sleep(2000 * (attempt + 1));
      continue;
    }
    if (!res.ok) throw new Error(`CLOB fetch failed: ${res.status} ${await res.text()}`);
    const body = ClobHistoryResponse.parse(await res.json());
    const points: PricePoint[] = (body.history ?? []).map((h) => ({
      ts: new Date(h.t * 1000).toISOString(),
      mid: h.p
    }));
    writeClobCache(tokenId, points);
    return { points, cacheHit: false };
  }
  throw new Error(`CLOB rate-limited after retries: ${tokenId}`);
}
