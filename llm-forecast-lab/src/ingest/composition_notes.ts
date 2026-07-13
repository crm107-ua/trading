export const HEURISTIC_DISCLAIMER =
  "Cota inferior por patrón (regex no excluyente en slug+question). No es composición real; subestima deportes con slugs de liga (lal-, spl-, tur-, fl1-…) y otros sin keywords.";

export const TEMPORAL_DISCLAIMER =
  "Estratificación proporcional por trimestre refleja la concentración temporal del universo; el veredicto es esencialmente sobre el año dominante.";

export const DATE_RANGE_CASCADE_NOTE =
  "afterDateRange en cascada re-verifica lo que Gamma ya acota vía end_date_min/max en keyset (defensa en profundidad; 100% es esperado, no evidencia de filtro muerto).";

export type SlugHeuristicPattern = { name: string; re: RegExp };

export function slugHeuristicPatterns(): SlugHeuristicPattern[] {
  return [
    {
      name: "crypto_price",
      re: /(price-of-|ethereum-above|eth-reach|btc-|bitcoin-|solana-|xrp-|doge-|cryptopunks|crypto)/i
    },
    {
      name: "elections_politics",
      re: /(president|senate|congress|trump|biden|election|endorse|prime-minister|governor|vote-to-confirm)/i
    },
    {
      name: "geopolitics_war",
      re: /(russia|ukraine|china|iran|israel|gaza|capture|tariff|maduro|ceasefire|nato|strike-on)/i
    },
    {
      name: "sports",
      re: new RegExp(
        [
          "march-madness",
          "nba-",
          "nfl-",
          "mlb-",
          "nhl-",
          "lal-",
          "spl-",
          "tur-",
          "fl1-",
          "epl-",
          "uel-",
          "mls-",
          "sea-",
          "bun-",
          "ere-",
          "ufc-",
          "f1-",
          "super-bowl",
          "final-four",
          "champions-league",
          "world-series",
          "world-cup",
          "lol-worlds",
          "eurobasket",
          "kentucky-derby",
          "pdc-world",
          "-win-on-20"
        ].join("|"),
        "i"
      )
    },
    { name: "ai_tech", re: /(ai-model|anthropic|deepseek|openai|gpt-|eip-|tesla-deliver)/i },
    { name: "elon_tweet_noise", re: /elon-tweet/i }
  ];
}

export type CompositionItem = {
  slug: string;
  question: string;
  resolution_date: string;
};

function pct(n: number, base: number): number {
  return base > 0 ? Number(((n / base) * 100).toFixed(2)) : 0;
}

export function computeSlugHeuristics(items: CompositionItem[]) {
  const patterns = slugHeuristicPatterns();
  const counts: Record<string, number> = Object.fromEntries(patterns.map((p) => [p.name, 0]));
  let unmatched = 0;

  for (const item of items) {
    const text = `${item.slug} ${item.question}`;
    let hit = false;
    for (const p of patterns) {
      if (p.re.test(text)) {
        counts[p.name] = (counts[p.name] ?? 0) + 1;
        hit = true;
      }
    }
    if (!hit) unmatched += 1;
  }

  const n = items.length;
  return {
    disclaimer: HEURISTIC_DISCLAIMER,
    method: "pattern_lower_bound_non_exclusive",
    n,
    counts: Object.fromEntries(
      patterns.map((p) => [p.name, { n: counts[p.name] ?? 0, pctOfEligible: pct(counts[p.name] ?? 0, n) }])
    ),
    unmatched: { n: unmatched, pctOfEligible: pct(unmatched, n) }
  };
}

export function computeTemporalConcentration(items: CompositionItem[]) {
  const byYear: Record<string, number> = {};
  for (const item of items) {
    const yr = item.resolution_date.slice(0, 4) || "UNKNOWN";
    byYear[yr] = (byYear[yr] ?? 0) + 1;
  }

  const n = items.length;
  const byResolutionYear = Object.entries(byYear)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([year, count]) => ({ year, n: count, pctOfEligible: pct(count, n) }));

  const dominant = byResolutionYear.reduce(
    (best, cur) => (cur.n > best.n ? cur : best),
    { year: "UNKNOWN", n: 0, pctOfEligible: 0 }
  );

  return {
    disclaimer: TEMPORAL_DISCLAIMER,
    n,
    byResolutionYear,
    dominantYear: dominant.year,
    dominantYearPct: dominant.pctOfEligible,
    verdictScopeNote: `Veredicto esencialmente sobre preguntas resueltas en ${dominant.year} (~${dominant.pctOfEligible}% del elegible).`
  };
}

export function buildCompositionAnnotations(items: CompositionItem[]) {
  return {
    slugHeuristics: computeSlugHeuristics(items),
    temporalConcentration: computeTemporalConcentration(items),
    afterDateRangeNote: DATE_RANGE_CASCADE_NOTE
  };
}
