export function mulberry32(seed: number): () => number {
  let a = seed | 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function bootstrapMeanDiffCi(args: {
  a: number[];
  b: number[];
  iterations: number;
  seed: number;
  ci: number; // 0.95
}): { meanDiff: number; lo: number; hi: number } {
  if (args.a.length !== args.b.length) throw new Error("bootstrap arrays must match length");
  const n = args.a.length;
  if (n === 0) return { meanDiff: 0, lo: 0, hi: 0 };
  const diffs = args.a.map((x, i) => x - (args.b[i] ?? 0));
  const mean = diffs.reduce((s, x) => s + x, 0) / n;

  const rng = mulberry32(args.seed);
  const samples: number[] = [];
  for (let it = 0; it < args.iterations; it++) {
    let acc = 0;
    for (let j = 0; j < n; j++) {
      const k = Math.floor(rng() * n);
      acc += diffs[k] ?? 0;
    }
    samples.push(acc / n);
  }
  samples.sort((x, y) => x - y);
  const alpha = 1 - args.ci;
  const loIdx = Math.floor((alpha / 2) * samples.length);
  const hiIdx = Math.floor((1 - alpha / 2) * samples.length) - 1;
  return {
    meanDiff: mean,
    lo: samples[Math.max(0, Math.min(samples.length - 1, loIdx))] ?? mean,
    hi: samples[Math.max(0, Math.min(samples.length - 1, hiIdx))] ?? mean
  };
}

