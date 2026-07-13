export type CalibrationBin = {
  bin: number; // 0..9 for 10 bins
  n: number;
  avgP: number;
  freqY: number;
};

export function calibrationBins(args: { ps: number[]; ys: Array<0 | 1>; bins?: number }): CalibrationBin[] {
  const bins = args.bins ?? 10;
  const counts = Array.from({ length: bins }, () => ({ n: 0, sumP: 0, sumY: 0 }));
  for (let i = 0; i < args.ps.length; i++) {
    const p = args.ps[i] ?? 0.5;
    const y = args.ys[i] ?? 0;
    const b = Math.min(bins - 1, Math.max(0, Math.floor(p * bins)));
    const c = counts[b]!;
    c.n += 1;
    c.sumP += p;
    c.sumY += y;
  }
  return counts.map((c, idx) => ({
    bin: idx,
    n: c.n,
    avgP: c.n === 0 ? 0 : c.sumP / c.n,
    freqY: c.n === 0 ? 0 : c.sumY / c.n
  }));
}

export function ece(bins: CalibrationBin[]): number {
  const nTotal = bins.reduce((a, b) => a + b.n, 0);
  if (nTotal === 0) return 0;
  let acc = 0;
  for (const b of bins) {
    acc += (b.n / nTotal) * Math.abs(b.avgP - b.freqY);
  }
  return acc;
}

