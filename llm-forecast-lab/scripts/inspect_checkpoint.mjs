import Database from "better-sqlite3";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const db = new Database("data/lab.sqlite", { readonly: true });

// 1) Date range on raw gamma
const stats = db.prepare(`
  SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN json_extract(payload_json,'$.endDate') IS NULL THEN 1 ELSE 0 END) AS null_end,
    MIN(json_extract(payload_json,'$.endDate')) AS min_end,
    MAX(json_extract(payload_json,'$.endDate')) AS max_end,
    SUM(CASE WHEN json_extract(payload_json,'$.endDate') < '2024-01-01' THEN 1 ELSE 0 END) AS before_2024,
    SUM(CASE WHEN json_extract(payload_json,'$.endDate') > '2026-12-31' THEN 1 ELSE 0 END) AS after_2026
  FROM gamma_markets_raw
`).get();

const byYear = db.prepare(`
  SELECT substr(json_extract(payload_json,'$.endDate'),1,4) AS yr, COUNT(*) AS n
  FROM gamma_markets_raw
  WHERE json_extract(payload_json,'$.endDate') IS NOT NULL
  GROUP BY yr ORDER BY yr
`).all();

console.log("=== DATE_RANGE_RAW ===");
console.log(JSON.stringify(stats, null, 2));
console.log("=== BY_YEAR ===");
console.log(JSON.stringify(byYear, null, 2));

// Compare string vs Date.parse filter logic
const evalFrozen = JSON.parse(readFileSync("config/eval_frozen.json", "utf8"));
const from = Date.parse(evalFrozen.protocol.selection.dateRange.resolutionFrom);
const to = Date.parse(evalFrozen.protocol.selection.dateRange.resolutionTo);

function parseJsonArrayField(raw) {
  if (raw == null) return [];
  if (Array.isArray(raw)) return raw.map((x) => String(x));
  if (typeof raw === "string") {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map((x) => String(x)) : [];
  }
  return [];
}

function isBinaryYesNoOutcomes(outcomes) {
  try {
    const arr = parseJsonArrayField(outcomes);
    const s = arr.map((x) => x.toLowerCase());
    return s.length === 2 && s.includes("yes") && s.includes("no");
  } catch {
    return false;
  }
}

function passesDateRange(m) {
  if (!m.endDate) return false;
  const resTs = Date.parse(String(m.endDate));
  return Number.isFinite(resTs) && resTs >= from && resTs <= to;
}

function marketDurationDays(m) {
  const end = m.endDate ? Date.parse(String(m.endDate)) : NaN;
  const startRaw = m.startDate ?? m.createdAt;
  const start = startRaw ? Date.parse(String(startRaw)) : NaN;
  if (!Number.isFinite(end) || !Number.isFinite(start) || end <= start) return null;
  return (end - start) / (24 * 3600 * 1000);
}

function passesDuration(m) {
  const dur = marketDurationDays(m);
  return dur !== null && dur >= evalFrozen.protocol.selection.minMarketDurationDays;
}

function passesSelection(m) {
  if (!isBinaryYesNoOutcomes(m.outcomes) || !m.endDate) return false;
  if (Boolean(m.isDisputed ?? m.isResolutionDisputed ?? m.hasDispute ?? false)) return false;
  if (!passesDateRange(m)) return false;
  if (!passesDuration(m)) return false;
  const liq = Number(m.liquidityNum ?? m.volumeNum ?? 0);
  if (liq < evalFrozen.protocol.selection.minLiquidityProxy) return false;
  return true;
}

function isEligibleForModel(resolutionDateIso, trainingCutoff) {
  const margin = evalFrozen.protocol.integrity.safetyMarginDays;
  const res = Date.parse(resolutionDateIso);
  const cutoff = Date.parse(trainingCutoff);
  const marginMs = margin * 24 * 3600 * 1000;
  return Number.isFinite(res) && Number.isFinite(cutoff) && res - marginMs > cutoff;
}

const rows = db.prepare("select slug, payload_json from gamma_markets_raw").all();
let afterDateRange = 0;
let outsideDateRange = 0;
const outsideSamples = [];
const eligible = [];

for (const r of rows) {
  const m = JSON.parse(r.payload_json);
  if (passesDateRange(m)) afterDateRange += 1;
  else if (m.endDate) {
    outsideDateRange += 1;
    if (outsideSamples.length < 5) outsideSamples.push({ slug: r.slug, endDate: m.endDate });
  }
  if (passesSelection(m) && isEligibleForModel(String(m.endDate), "2024-06-01")) {
    eligible.push({ slug: r.slug, question: m.question, endDate: m.endDate, category: m.category });
  }
}

console.log("=== FILTER_REPLAY ===");
console.log(JSON.stringify({
  raw: rows.length,
  afterDateRange,
  outsideDateRange,
  outsideSamples,
  intersectionEligible: eligible.length
}, null, 2));

// 2) 20 random slugs from eligible (deterministic seed)
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rng = mulberry32(20260713);
const pool = [...eligible];
for (let i = pool.length - 1; i > 0; i--) {
  const j = Math.floor(rng() * (i + 1));
  [pool[i], pool[j]] = [pool[j], pool[i]];
}
const sample20 = pool.slice(0, 20);
console.log("=== SAMPLE_20_SLUGS ===");
for (const s of sample20) {
  console.log(JSON.stringify(s));
}

console.log("=== AFTER_2026_STRING_VS_PARSE ===");
const after2026 = db.prepare(`
  select slug, json_extract(payload_json,'$.endDate') as endDate
  from gamma_markets_raw
  where json_extract(payload_json,'$.endDate') > '2026-12-31'
  limit 10
`).all();
const toTs = Date.parse(evalFrozen.protocol.selection.dateRange.resolutionTo);
const fromTs = Date.parse(evalFrozen.protocol.selection.dateRange.resolutionFrom);
const after2026Parsed = after2026.map((r) => {
  const ts = Date.parse(r.endDate);
  return { ...r, parsed: ts, passes: Number.isFinite(ts) && ts >= fromTs && ts <= toTs };
});
const after2026Count = db.prepare(`
  select count(*) as n from gamma_markets_raw
  where json_extract(payload_json,'$.endDate') > '2026-12-31'
`).get();
console.log(JSON.stringify({ after2026Count, samples: after2026Parsed }, null, 2));

// Slug heuristics on full eligible pool
// Slug heuristics — keep in sync with src/ingest/composition_notes.ts
const patterns = [
  { name: "crypto_price", re: /(price-of-|ethereum-above|eth-reach|btc-|bitcoin-|solana-|xrp-|doge-|cryptopunks|crypto)/i },
  { name: "elections_politics", re: /(president|senate|congress|trump|biden|election|endorse|prime-minister|governor|vote-to-confirm)/i },
  { name: "geopolitics_war", re: /(russia|ukraine|china|iran|israel|gaza|capture|tariff|maduro|ceasefire|nato|strike-on)/i },
  {
    name: "sports",
    re: /(march-madness|nba-|nfl-|mlb-|nhl-|lal-|spl-|tur-|fl1-|epl-|uel-|mls-|sea-|bun-|ere-|ufc-|f1-|super-bowl|final-four|champions-league|world-series|world-cup|lol-worlds|eurobasket|kentucky-derby|pdc-world|-win-on-20)/i
  },
  { name: "ai_tech", re: /(ai-model|anthropic|deepseek|openai|gpt-|eip-|tesla-deliver)/i },
  { name: "elon_tweet_noise", re: /elon-tweet/i }
];
const HEURISTIC_DISCLAIMER =
  "Cota inferior por patrón (regex no excluyente). No es composición real; subestima categorías sin keywords.";
const counts = Object.fromEntries(patterns.map((p) => [p.name, 0]));
let unmatched = 0;
for (const e of eligible) {
  const slugQ = `${e.slug} ${e.question}`;
  let hit = false;
  for (const p of patterns) {
    if (p.re.test(slugQ)) {
      counts[p.name] += 1;
      hit = true;
    }
  }
  if (!hit) unmatched += 1;
}
console.log("=== SLUG_HEURISTICS_ELIGIBLE ===");
console.log(
  JSON.stringify(
    { disclaimer: HEURISTIC_DISCLAIMER, n: eligible.length, counts, unmatched, unmatchedPct: Number(((unmatched / eligible.length) * 100).toFixed(2)) },
    null,
    2
  )
);

console.log("=== DB_STATE ===");
const rq = db.prepare("select count(*) as n from run_questions").get();
const qq = db.prepare("select count(*) as n from questions").get();
const meta = db.prepare("select k, v from meta where k like 'gamma_keyset%'").all();
console.log(JSON.stringify({ run_questions: rq, questions: qq, keyset_meta: meta }, null, 2));

console.log("=== DEDUP_SANITY ===");
const dedup = db.prepare(`
  SELECT
    COUNT(*) AS total,
    COUNT(DISTINCT slug) AS distinct_slug,
    COUNT(DISTINCT market_id) AS distinct_market_id,
    COUNT(DISTINCT json_extract(payload_json,'$.id')) AS distinct_payload_id
  FROM gamma_markets_raw
`).get();
const slugDupes = db.prepare(`
  SELECT slug, COUNT(*) AS n FROM gamma_markets_raw GROUP BY slug HAVING n > 1 LIMIT 5
`).all();
const marketIdDupes = db.prepare(`
  SELECT market_id, COUNT(DISTINCT slug) AS slug_n
  FROM gamma_markets_raw
  GROUP BY market_id
  HAVING slug_n > 1
  LIMIT 5
`).all();
console.log(
  JSON.stringify(
    {
      ...dedup,
      ok:
        dedup.total === dedup.distinct_slug &&
        dedup.total === dedup.distinct_market_id &&
        dedup.total === dedup.distinct_payload_id,
      slugDupesSample: slugDupes,
      marketIdMultiSlugSample: marketIdDupes
    },
    null,
    2
  )
);

db.close();
