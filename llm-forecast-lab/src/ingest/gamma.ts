import { z } from "zod";

export const GAMMA_BASE_URL = "https://gamma-api.polymarket.com";

export const GammaMarketSchema = z.object({
  id: z.string(),
  slug: z.string().optional(),
  question: z.string(),
  description: z.string().nullable().optional(),
  category: z.string().nullable().optional(),
  closed: z.boolean().optional(),
  startDate: z.string().nullable().optional(),
  createdAt: z.string().nullable().optional(),
  endDate: z.string().nullable().optional(),
  outcomes: z.any().optional(),
  outcomePrices: z.any().optional(),
  clobTokenIds: z.any().optional(),
  volumeNum: z.number().nullable().optional(),
  liquidityNum: z.number().nullable().optional(),
  isDisputed: z.boolean().nullable().optional(),
  isResolutionDisputed: z.boolean().nullable().optional(),
  hasDispute: z.boolean().optional()
});
export type GammaMarket = z.infer<typeof GammaMarketSchema>;

const GammaKeysetResponse = z.object({
  markets: z.array(GammaMarketSchema).optional(),
  next_cursor: z.string().nullable().optional()
});

export type KeysetFetchReport = {
  markets: GammaMarket[];
  pages: number;
  dedupedUnique: number;
};

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export function parseJsonArrayField(raw: unknown): string[] {
  if (raw == null) return [];
  if (Array.isArray(raw)) return raw.map((x) => String(x));
  if (typeof raw === "string") {
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.map((x) => String(x)) : [];
  }
  return [];
}

export function isBinaryYesNoOutcomes(outcomes: unknown): boolean {
  try {
    const arr = parseJsonArrayField(outcomes);
    const s = arr.map((x) => x.toLowerCase());
    return s.length === 2 && s.includes("yes") && s.includes("no");
  } catch {
    return false;
  }
}

export function resolvedYesNoFromOutcomePrices(m: GammaMarket): "YES" | "NO" | null {
  const outcomes = parseJsonArrayField(m.outcomes);
  const prices = parseJsonArrayField(m.outcomePrices).map((x) => Number(x));
  if (outcomes.length !== 2 || prices.length !== 2) return null;
  const yesIdx = outcomes.findIndex((o) => o.toLowerCase() === "yes");
  const noIdx = outcomes.findIndex((o) => o.toLowerCase() === "no");
  if (yesIdx < 0 || noIdx < 0) return null;
  const yesPrice = prices[yesIdx] ?? 0;
  const noPrice = prices[noIdx] ?? 0;
  if (yesPrice >= 0.99 && noPrice <= 0.01) return "YES";
  if (noPrice >= 0.99 && yesPrice <= 0.01) return "NO";
  return null;
}

export function yesTokenId(m: GammaMarket): string | null {
  const outcomes = parseJsonArrayField(m.outcomes);
  const tokens = parseJsonArrayField(m.clobTokenIds);
  const yesIdx = outcomes.findIndex((o) => o.toLowerCase() === "yes");
  if (yesIdx < 0 || yesIdx >= tokens.length) return null;
  return tokens[yesIdx] ?? null;
}

export async function fetchJsonWithRetry(url: string, opts?: { pagePauseMs?: number }): Promise<unknown> {
  for (let attempt = 0; attempt < 8; attempt++) {
    const res = await fetch(url);
    if (res.status === 429 || res.status === 403) {
      const backoff = attempt < 3 ? 2000 * (attempt + 1) : 60_000;
      await sleep(backoff);
      continue;
    }
    if (!res.ok) throw new Error(`Gamma fetch failed: ${res.status} ${await res.text()}`);
    if (opts?.pagePauseMs) await sleep(opts.pagePauseMs);
    return res.json();
  }
  throw new Error(`Gamma fetch rate-limited/blocked after retries: ${url}`);
}

export async function fetchMarketsViaKeyset(args: {
  from: string;
  to: string;
  gammaBaseUrl?: string;
  pagePauseMs?: number;
  onPage?: (info: { page: number; pageSize: number; total: number }) => void;
}): Promise<KeysetFetchReport> {
  const gammaBaseUrl = args.gammaBaseUrl ?? GAMMA_BASE_URL;
  const bySlug = new Map<string, GammaMarket>();
  let cursor: string | null = null;
  let pages = 0;

  while (true) {
    let url =
      `${gammaBaseUrl}/markets/keyset?closed=true&limit=100&order=end_date&ascending=true` +
      `&end_date_min=${encodeURIComponent(args.from)}` +
      `&end_date_max=${encodeURIComponent(args.to)}`;
    if (cursor) url += `&after_cursor=${encodeURIComponent(cursor)}`;

    const body = GammaKeysetResponse.parse(
      await fetchJsonWithRetry(url, { pagePauseMs: args.pagePauseMs ?? 500 })
    );
    const page = body.markets ?? [];
    if (page.length === 0) break;

    for (const m of page) {
      const key = m.slug ?? m.id;
      if (!bySlug.has(key)) bySlug.set(key, m);
    }

    pages += 1;
    args.onPage?.({ page: pages, pageSize: page.length, total: bySlug.size });
    cursor = body.next_cursor ?? null;
    if (!cursor) break;
  }

  return { markets: [...bySlug.values()], pages, dedupedUnique: bySlug.size };
}
