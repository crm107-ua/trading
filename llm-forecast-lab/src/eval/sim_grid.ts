import type Database from "better-sqlite3";
import { loadSimPaperConfig, runSimPaper } from "./sim_paper.js";

export type SimGridRow = {
  minNetEdge: number;
  netPnlUsdc: number;
  trades: number;
  winRate: number;
  returnPct: number;
};

export type SimGridReport = {
  verdictBinding: false;
  hypothesis: string;
  grid: SimGridRow[];
  best: SimGridRow | null;
  recommendedMinNetEdge: number | null;
};

/** Post-verdict exploratory only — not part of Day D bundle. */
export function runSimPaperGrid(
  db: Database.Database,
  args: {
    pipeline: string;
    from?: number;
    to?: number;
    step?: number;
  }
): SimGridReport {
  const base = loadSimPaperConfig("./config");
  const from = args.from ?? 0.01;
  const to = args.to ?? 0.1;
  const step = args.step ?? 0.01;
  const grid: SimGridRow[] = [];

  for (let e = from; e <= to + 1e-9; e += step) {
    const rep = runSimPaper(db, {
      pipeline: args.pipeline,
      cfg: { ...base, minNetEdge: Number(e.toFixed(4)) }
    });
    grid.push({
      minNetEdge: rep.config.minNetEdge,
      netPnlUsdc: rep.summary.netPnlUsdc,
      trades: rep.summary.trades,
      winRate: rep.summary.winRate,
      returnPct: rep.summary.returnPct
    });
  }

  const withTrades = grid.filter((g) => g.trades >= 5);
  const pool = withTrades.length > 0 ? withTrades : grid.filter((g) => g.trades > 0);
  const best =
    pool.length === 0
      ? null
      : pool.reduce((a, b) => (b.netPnlUsdc > a.netPnlUsdc ? b : a));

  return {
    verdictBinding: false,
    hypothesis: base.hypothesis,
    grid,
    best,
    recommendedMinNetEdge: best?.minNetEdge ?? null
  };
}
