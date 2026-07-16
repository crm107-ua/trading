from pathlib import Path

p = Path(__file__).with_name("paper_maker.py")
t = p.read_text(encoding="utf-8")
needle = '"fast_path_min_spread_cents": float(self.cfg.get("fast_path_min_spread_cents", 1.0)),\n            }'
insert = (
    '"fast_path_min_spread_cents": float(self.cfg.get("fast_path_min_spread_cents", 1.0)),\n'
    '                "edge_abs": abs(fair - ((state["best_bid"] + state["best_ask"]) / 2)) '
    'if state["best_bid"] is not None and state["best_ask"] is not None else None,\n'
    '                "min_edge": float(self.cfg.get("min_edge", 0.03)),\n'
    "            }"
)
if needle not in t:
    raise SystemExit("needle not found")
if "edge_abs" in t:
    print("already patched")
else:
    p.write_text(t.replace(needle, insert, 1), encoding="utf-8")
    print("patched")
