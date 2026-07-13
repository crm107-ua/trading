export function brier(p: number, y: 0 | 1): number {
  const e = p - y;
  return e * e;
}

export function logLoss(p: number, y: 0 | 1): number {
  // Clip to avoid infinities.
  const eps = 1e-12;
  const pc = Math.min(1 - eps, Math.max(eps, p));
  return y === 1 ? -Math.log(pc) : -Math.log(1 - pc);
}

export type ScoreRow = {
  forecastId: string;
  y: 0 | 1;
  brier: number;
  logLoss: number;
};

