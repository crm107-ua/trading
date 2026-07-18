#!/usr/bin/env python3
"""Fase C — compara metodologías en paper (NO valida live).

    python -m polymarket.research.local_lab.paper_oos_compare --minutes 3 --sessions 2
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from polymarket.web_lab.catalog import FEATURED, load_scaled_config

POLY = Path(__file__).resolve().parents[2]
ROOT = POLY.parent
OUT = POLY / "data_local" / "local_lab" / "paper_oos"
# Solo las que el plan cita para OOS (no micro live)
OOS_IDS = ("t4_exact", "t4_risk_up", "fuse_v3")


def _run_batch(cfg_path: Path, sessions: int, minutes: float, out_tag: str) -> dict:
    cmd = [
        sys.executable,
        "-u",
        "-m",
        "polymarket.research.local_lab.batch_paper_eval",
        "--strategy",
        "maker_edge",
        "--config",
        str(cfg_path),
        "--sessions",
        str(sessions),
        "--minutes",
        str(minutes),
        "--target",
        "0.5",
    ]
    # batch_paper_eval writes under data_local; capture stdout for nets
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=3600)
    text = (p.stdout or "") + (p.stderr or "")
    nets: list[float] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("net="):
            try:
                # net=+0.00 fills=0
                part = line.split()[0].replace("net=", "")
                nets.append(float(part))
            except ValueError:
                pass
    return {
        "ok": p.returncode in (0, 1),
        "exit": p.returncode,
        "nets": nets,
        "total": round(sum(nets), 4) if nets else 0.0,
        "wr": (
            round(sum(1 for n in nets if n > 1e-9) / len(nets), 4) if nets else None
        ),
        "worst": min(nets) if nets else None,
        "fills_hint": text.count("fills="),
        "starve_hints": text.count("wait_mid_hi") + text.count("wait_edge"),
        "tail": text[-1200:],
        "tag": out_tag,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--minutes", type=float, default=6.0)
    ap.add_argument("--capital", type=float, default=100.0)
    ap.add_argument(
        "--ids",
        default=",".join(OOS_IDS),
        help="strategy ids comma-separated",
    )
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    featured = {f["id"]: f for f in FEATURED}
    report: dict = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Paper OOS — no valida ejecución live",
        "sessions": args.sessions,
        "minutes": args.minutes,
        "capital": args.capital,
        "strategies": [],
    }
    for sid in ids:
        if sid not in featured:
            report["strategies"].append({"id": sid, "error": "not in FEATURED"})
            continue
        print(f"=== paper OOS {sid} ===", flush=True)
        cfg, meta = load_scaled_config(sid, float(args.capital))
        cfg_path = OUT / f"cfg_{sid}_{stamp}.json"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        res = _run_batch(cfg_path, args.sessions, args.minutes, sid)
        row = {
            "id": sid,
            "name": meta.get("name"),
            "badge": featured[sid].get("badge"),
            **{k: res[k] for k in res if k != "tail"},
        }
        report["strategies"].append(row)
        print(
            f"  total={row.get('total')} wr={row.get('wr')} worst={row.get('worst')}",
            flush=True,
        )

    # Ranking por total luego worst
    ranked = [s for s in report["strategies"] if "total" in s]

    def _rank_key(x: dict) -> tuple:
        tot = x.get("total")
        worst = x.get("worst")
        # 0.0 is valid (not missing) — no usar `or`
        t = float(tot) if tot is not None else -999.0
        w = float(worst) if worst is not None else -999.0
        return (t, w)

    ranked.sort(key=_rank_key, reverse=True)
    report["pick_top2"] = [
        {"id": s["id"], "total": s.get("total"), "wr": s.get("wr"), "worst": s.get("worst")}
        for s in ranked[:2]
    ]
    out_path = OUT / f"compare_{stamp}.json"
    latest = OUT / "compare_latest.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_path), "pick_top2": report["pick_top2"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
