"""
Mathematical / probabilistic study for paper maker edge (real-feeds mode).

EV model (one fill + mid exit):
  Bid fill at p_bid, exit at mid:
    pnl = size * (mid - p_bid)
  Accept bid only if mid <= fair - ε  (market cheap) and p_bid <= mid + τ
  ⇒ E[pnl | accept] ≈ size * (spread/2 + mispricing)

Win probability under Gaussian mid noise σ around fair:
  P(mid > p_bid) for long ≈ Φ((fair - p_bid)/σ) if mid~N(fair,σ²)
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass(frozen=True)
class EdgeParams:
    half_spread: float
    min_edge: float  # |fair - mid| minimum to quote
    toxic_tol: float  # reject fill if mid is toxic vs fill price
    size: float
    sigma_mid: float  # mid noise vs fair


def p_win_bid(params: EdgeParams, fair: float = 0.5) -> float:
    """P(mid > bid) when mid ~ N(fair, σ²), bid = fair - hs - min_edge/2 approx."""
    bid = fair - params.half_spread - params.min_edge
    # P(mid > bid) = 1 - Φ((bid - fair)/σ) = Φ((fair - bid)/σ)
    z = (fair - bid) / max(params.sigma_mid, 1e-6)
    return norm_cdf(z)


def expected_pnl_bid(params: EdgeParams, fair: float = 0.5) -> float:
    """E[size*(mid-bid)] with mid~N(fair,σ²)."""
    bid = fair - params.half_spread - params.min_edge
    # E[mid - bid] = fair - bid
    return params.size * (fair - bid)


def monte_carlo_session(
    params: EdgeParams,
    *,
    n_fills: int,
    n_sims: int = 5000,
    seed: int = 42,
) -> dict[str, Any]:
    rng = random.Random(seed)
    nets: list[float] = []
    for _ in range(n_sims):
        pnl = 0.0
        for _f in range(n_fills):
            fair = rng.uniform(0.25, 0.75)
            mid = rng.gauss(fair, params.sigma_mid)
            mid = max(0.02, min(0.98, mid))
            # selective: only trade if |fair-mid| >= min_edge
            if abs(fair - mid) < params.min_edge:
                continue
            if mid < fair:  # market cheap → bid
                bid = mid  # join touch approx
                if mid < bid - params.toxic_tol:
                    continue
                # exit at new mid'
                mid2 = max(0.02, min(0.98, rng.gauss(fair, params.sigma_mid)))
                pnl += params.size * (mid2 - bid)
            else:  # market rich → ask
                ask = mid
                if mid > ask + params.toxic_tol:
                    continue
                mid2 = max(0.02, min(0.98, rng.gauss(fair, params.sigma_mid)))
                pnl += params.size * (ask - mid2)
        nets.append(pnl)
    nets.sort()
    wins = sum(1 for x in nets if x > 0)
    return {
        "n_sims": n_sims,
        "n_fills_target": n_fills,
        "win_rate": wins / n_sims,
        "avg_pnl": sum(nets) / n_sims,
        "p05": nets[int(0.05 * n_sims)],
        "p50": nets[int(0.50 * n_sims)],
        "p95": nets[int(0.95 * n_sims)],
        "params": params.__dict__,
    }


def grid_search(
    *,
    min_edges: list[float],
    half_spreads: list[float],
    sigmas: list[float],
    n_fills: int = 8,
    n_sims: int = 3000,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for me in min_edges:
        for hs in half_spreads:
            for sig in sigmas:
                p = EdgeParams(half_spread=hs, min_edge=me, toxic_tol=0.01, size=6.0, sigma_mid=sig)
                r = monte_carlo_session(p, n_fills=n_fills, n_sims=n_sims)
                r["score"] = r["win_rate"] * 2.0 + r["avg_pnl"] * 0.1  # prefer WR then pnl
                rows.append(r)
    rows.sort(key=lambda x: (x["win_rate"], x["avg_pnl"]), reverse=True)
    return rows


def bootstrap_ci(xs: list[float], n_boot: int = 2000, seed: int = 0) -> dict[str, float]:
    if not xs:
        return {"mean": 0.0, "lo": 0.0, "hi": 0.0}
    rng = random.Random(seed)
    n = len(xs)
    means = []
    for _ in range(n_boot):
        sample = [xs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    return {
        "mean": sum(xs) / n,
        "lo": means[int(0.025 * n_boot)],
        "hi": means[int(0.975 * n_boot)],
    }


def run_study(out_path: Path | None = None) -> dict[str, Any]:
    rows = grid_search(
        min_edges=[0.01, 0.02, 0.03, 0.04, 0.05],
        half_spreads=[0.01, 0.015, 0.02, 0.025],
        sigmas=[0.02, 0.03, 0.05],
        n_fills=10,
        n_sims=4000,
    )
    top = rows[:10]
    best = top[0]
    report = {
        "title": "Maker edge Monte Carlo grid (real-feeds assumptions)",
        "best": best,
        "top10": top,
        "notes": [
            "Assumes selective quoting when |fair-mid|>=min_edge",
            "Exit at refreshed mid ~ N(fair,σ)",
            "Not a guarantee of live PnL; guides parameter search",
        ],
    }
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    rep = run_study(root / "data_local" / "local_lab" / "edge_study_mc.json")
    print(json.dumps({"best_win_rate": rep["best"]["win_rate"], "best_avg_pnl": rep["best"]["avg_pnl"], "best_params": rep["best"]["params"]}, indent=2))
