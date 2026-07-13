#!/usr/bin/env python3
"""Phase A health check — exit 1 if any feed stale beyond threshold."""

from __future__ import annotations

import json
import sys

from polymarket.research.collectors.recording_common import (
    load_phase_a_config,
    now_ns,
    resolve_data_root,
)


def main() -> None:
    cfg = load_phase_a_config()
    root = resolve_data_root(cfg)
    manifest_path = root / "manifest.json"
    threshold_min = float(cfg.get("stale_alert_minutes", 10))

    if not manifest_path.exists():
        print(f"FAIL: no manifest at {manifest_path}")
        sys.exit(1)

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    feeds = data.get("feeds") or {}
    now = now_ns()
    failed = False

    for name in ("btc", "clob"):
        feed = feeds.get(name)
        if not feed:
            print(f"FAIL: feed '{name}' missing in manifest")
            failed = True
            continue
        last = int(feed.get("last_ts_ns") or 0)
        if last <= 0:
            print(f"FAIL: feed '{name}' has no timestamps yet")
            failed = True
            continue
        stale_min = (now - last) / 1_000_000_000 / 60
        if stale_min > threshold_min:
            print(f"FAIL: feed '{name}' stale {stale_min:.1f}m > {threshold_min}m")
            failed = True
        else:
            print(f"OK: feed '{name}' stale {stale_min:.1f}m rows={feed.get('rows_total')}")

    gaps_btc = len((feeds.get("btc") or {}).get("gaps") or [])
    gaps_clob = len((feeds.get("clob") or {}).get("gaps") or [])
    print(f"Gaps: btc={gaps_btc} clob={gaps_clob}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
