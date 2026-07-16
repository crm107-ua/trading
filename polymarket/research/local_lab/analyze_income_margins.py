#!/usr/bin/env python3
"""Research: margin quality of recent income sessions."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "data_local" / "local_lab" / "maker_edge"
IDS = [
    "v2_120132_01",
    "v2_120132_02",
    "v2_120132_03",
    "v2_120132_04",
    "v2_120132_05",
    "v2_120132_06",
]


def main() -> None:
    rows = []
    for sid in IDS:
        d = ROOT / f"session_{sid}"
        if not (d / "fills.jsonl").exists():
            print(f"missing {sid}")
            continue
        fills = [
            json.loads(l)
            for l in (d / "fills.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
        edges = []
        notionals = []
        for f in fills:
            e = (f["fair"] - f["price"]) if f["side"] == "bid" else (f["price"] - f["fair"])
            edges.append(e)
            notionals.append(f["price"] * f["size"])
        net = float(rep.get("net_session_usdc", 0))
        risk = sum(notionals) / max(len(notionals), 1)
        margin = net / max(sum(notionals), 1e-9)
        rows.append((sid, net, len(fills), sum(edges) / max(len(edges), 1), margin, risk))
        print(
            f"{sid} net={net:+.2f} fills={len(fills)} "
            f"mean_edge={sum(edges)/max(len(edges),1):+.3f} "
            f"margin_on_notional={margin:.1%} avg_fill_notional={risk:.2f}"
        )
        if edges:
            hi = sorted(edges, reverse=True)[:3]
            print(f"  top_edges={ [round(x,3) for x in hi] } sizes={[f['size'] for f in fills[:6]]}")

    nets = [r[1] for r in rows]
    if nets:
        print(
            f"\nSUMMARY avg_net={sum(nets)/len(nets):+.2f} "
            f"WR={sum(1 for n in nets if n>0)/len(nets):.0%} "
            f"total={sum(nets):+.2f} on $100"
        )


if __name__ == "__main__":
    main()
