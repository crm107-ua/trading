import fs from "node:fs";
import path from "node:path";
import { z } from "zod";
import type { PricePoint } from "./types.js";

const CLOB_BASE_URL = "https://clob.polymarket.com";
const CHUNK_SECONDS = 13 * 24 * 3600;
const FIDELITY_MINUTES = 720;

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

function parseIsoSeconds(iso: string | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

function mergeHistory(chunks: PricePoint[][]): PricePoint[] {
  const byTs = new Map<string, PricePoint>();
  for (const chunk of chunks) {
    for (const p of chunk) byTs.set(p.ts, p);
  }
  return [...byTs.values()].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
}

async function fetchHistoryChunk(
  tokenId: string,
  startTs: number,
  endTs: number
): Promise<PricePoint[]> {
  const url =
    `${CLOB_BASE_URL}/prices-history?market=${encodeURIComponent(tokenId)}` +
    `&startTs=${startTs}&endTs=${endTs}&fidelity=${FIDELITY_MINUTES}`;

  for (let attempt = 0; attempt < 8; attempt++) {
    const res = await fetch(url);
    if (res.status === 429 || res.status === 403) {
      await sleep(2000 * (attempt + 1));
      continue;
    }
    if (!res.ok) throw new Error(`CLOB fetch failed: ${res.status} ${await res.text()}`);
    const body = ClobHistoryResponse.parse(await res.json());
    return (body.history ?? []).map((h) => ({
      ts: new Date(h.t * 1000).toISOString(),
      mid: h.p
    }));
  }
  throw new Error(`CLOB rate-limited after retries: ${tokenId}`);
}

export async function fetchPriceHistoryCached(
  tokenId: string,
  opts?: { startIso?: string; endIso?: string; force?: boolean }
): Promise<{
  points: PricePoint[];
  cacheHit: boolean;
}> {
  const cached = opts?.force ? null : readClobCache(tokenId);
  if (cached && cached.length > 0) return { points: cached, cacheHit: true };

  const endTs = parseIsoSeconds(opts?.endIso) ?? Math.floor(Date.now() / 1000);
  const startTs = parseIsoSeconds(opts?.startIso) ?? endTs - 30 * 24 * 3600;
  if (endTs <= startTs) return { points: [], cacheHit: false };

  const chunks: PricePoint[][] = [];
  for (let cur = startTs; cur < endTs; cur += CHUNK_SECONDS) {
    const chunkEnd = Math.min(cur + CHUNK_SECONDS, endTs);
    chunks.push(await fetchHistoryChunk(tokenId, cur, chunkEnd));
    await sleep(150);
  }

  const points = mergeHistory(chunks);
  writeClobCache(tokenId, points);
  return { points, cacheHit: false };
}
