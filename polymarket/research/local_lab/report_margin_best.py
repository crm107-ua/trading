#!/usr/bin/env python3
import json
from pathlib import Path

best_path = (
    Path(__file__).resolve().parents[2]
    / "data_local"
    / "local_lab"
    / "margin_max_best.json"
)
best = json.loads(best_path.read_text(encoding="utf-8"))
root = Path(__file__).resolve().parents[2] / "data_local" / "local_lab" / "maker_edge"
print(
    f"WR={best['win_rate']:.1%} avg={best['avg_net_usdc']:+.2f} "
    f"total={best.get('total_net')} losses={best['losses']} traded={best['sessions_with_fills']}"
)
for r in best["results"]:
    sid = r["session_id"]
    d = root / f"session_{sid}"
    if not (d / "fills.jsonl").exists():
        print(f"{sid} net={r['net']:+.2f} fills={r['fills']} (no file)")
        continue
    fills = [
        json.loads(l)
        for l in (d / "fills.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    notion = sum(f["price"] * f["size"] for f in fills) or 1e-9
    edges = [
        (f["fair"] - f["price"]) if f["side"] == "bid" else (f["price"] - f["fair"])
        for f in fills
    ]
    mean_e = sum(edges) / len(edges) if edges else 0.0
    print(
        f"{sid} net={r['net']:+.2f} fills={r['fills']} "
        f"margin={r['net']/notion:.1%} mean_edge={mean_e:+.3f} notional={notion:.1f}"
    )
