/**
 * v1 placeholder for ensemble aggregation. The evaluation framework supports it,
 * but we keep the implementation minimal until decomposed exists.
 */
export function trimmedMean(ps: number[], trimPct: number): number {
  if (ps.length === 0) return 0.5;
  const xs = [...ps].sort((a, b) => a - b);
  const k = Math.floor(xs.length * trimPct);
  const core = xs.slice(k, xs.length - k);
  const arr = core.length > 0 ? core : xs;
  return arr.reduce((s, x) => s + x, 0) / arr.length;
}

