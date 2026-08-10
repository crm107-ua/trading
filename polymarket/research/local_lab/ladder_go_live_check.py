#!/usr/bin/env python3
"""
Ladder-specific arm check (separate from maker pulse go_live_arm_check).

Validates:
  - champion / ultra-real paper income gate artifacts (if present)
  - micro-dry config sanity
  - env SAFE + signing readiness (derives CLOB keys if needed)
  - optional book_sim probe

Exit 0 = LADDER_DRY_READY (safe to run weather_ladder_live --mode clob_dry)
Exit 2 = not ready

  python -m polymarket.research.local_lab.ladder_go_live_check
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.execution.clob_live import ClobLiveClient, read_gates

POLY = Path(__file__).resolve().parents[2]
MICRO = POLY / "config" / "weather_ladder_micro_dry.json"
CHAMP = POLY / "config" / "weather_ladder_champion_v2.json"
ULTRA_DIR = POLY / "data_local" / "local_lab" / "ultra_real_campaign"
OUT = POLY / "data_local" / "local_lab" / "ladder_go_live"


def _latest_ultra() -> dict[str, Any] | None:
    if not ULTRA_DIR.is_dir():
        return None
    reps = sorted(ULTRA_DIR.glob("campaign_*/report.json"))
    if not reps:
        return None
    return json.loads(reps[-1].read_text(encoding="utf-8"))


def run_check(*, probe_book: bool = True) -> dict[str, Any]:
    load_repo_dotenv(override=True)
    checks: dict[str, bool] = {}
    notes: list[str] = []

    checks["micro_config_exists"] = MICRO.is_file()
    checks["champion_config_exists"] = CHAMP.is_file()
    micro = json.loads(MICRO.read_text(encoding="utf-8")) if MICRO.is_file() else {}
    checks["micro_cap_le_25"] = float((micro.get("live") or {}).get("max_capital_usdc") or 99) <= 25.0
    checks["micro_requires_dry"] = bool((micro.get("live") or {}).get("require_dry_run", False))
    checks["micro_open_only"] = bool(micro.get("open_only"))
    checks["micro_live_floors"] = bool(micro.get("enforce_live_floors"))

    ultra = _latest_ultra()
    if ultra:
        gate = (ultra.get("income_gate") or {})
        checks["ultra_paper_income_ready"] = bool(gate.get("passed"))
        notes.append(f"ultra_campaign={ultra.get('campaign_id')} verdict={gate.get('verdict')}")
    else:
        checks["ultra_paper_income_ready"] = False
        notes.append("no ultra_real campaign report found")

    # Env must be SAFE before check; dry harness arms temporarily itself.
    g0 = read_gates()
    checks["env_safe_armed0"] = not g0.armed
    checks["env_dry_default"] = bool(g0.dry_run)
    checks["signing_ready"] = bool(g0.signing_ready)

    derived = False
    bal = None
    bal_err = None
    if g0.signing_ready:
        try:
            # Temporarily allow connect+derive without arming
            cli = ClobLiveClient()
            cli.connect(derive_api_creds=True)
            derived = True
            try:
                bal = cli.balance_collateral_usdc()
            except Exception as exc:  # noqa: BLE001
                bal_err = f"{type(exc).__name__}: {exc}"
            g1 = read_gates()
            checks["clob_ready_after_derive"] = bool(g1.clob_ready)
        except Exception as exc:  # noqa: BLE001
            checks["clob_ready_after_derive"] = False
            notes.append(f"derive_failed: {type(exc).__name__}: {exc}")
    else:
        checks["clob_ready_after_derive"] = False

    book = None
    if probe_book and checks["micro_config_exists"]:
        from polymarket.research.local_lab.weather_ladder_live import run_book_sim

        book = run_book_sim(micro, session_id="go_live_probe")
        checks["book_sim_ran"] = True
        notes.append(
            f"book_sim accepted_n={book.get('accepted_n')} "
            f"near_miss={len(book.get('near_miss') or [])} "
            f"notional={book.get('notional_total_usdc')}"
        )
    else:
        checks["book_sim_ran"] = not probe_book

    # Required for DRY_READY (candidates optional — markets may be quiet)
    required = [
        "micro_config_exists",
        "champion_config_exists",
        "micro_cap_le_25",
        "micro_requires_dry",
        "micro_open_only",
        "micro_live_floors",
        "ultra_paper_income_ready",
        "env_safe_armed0",
        "env_dry_default",
        "signing_ready",
        "clob_ready_after_derive",
    ]
    passed = all(checks.get(k) for k in required)
    # Ensure we left SAFE
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    g_end = read_gates()

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "required": required,
        "passed": passed,
        "verdict": "LADDER_DRY_READY" if passed else "LADDER_NOT_READY",
        "balance_pusd": round(bal, 4) if bal is not None else None,
        "balance_error": bal_err,
        "derived_api_creds": derived,
        "notes": notes,
        "book_sim": {
            "accepted_n": (book or {}).get("accepted_n"),
            "events_open": (book or {}).get("events_open"),
            "near_miss": (book or {}).get("near_miss"),
            "notional_total_usdc": (book or {}).get("notional_total_usdc"),
            "accepted_slugs": [c["slug"] for c in (book or {}).get("candidates", [])],
        }
        if book
        else None,
        "safe_after": {"armed": g_end.armed, "dry_run": g_end.dry_run},
        "next_step": (
            "python -m polymarket.research.local_lab.weather_ladder_live --mode both"
            if passed
            else "Fix failed checks before micro dry-run"
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"check_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["path"] = str(path)
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-book-probe", action="store_true")
    args = p.parse_args()
    rep = run_check(probe_book=not args.no_book_probe)
    print(json.dumps(rep, indent=2))
    print(f"\nVERDICT: {rep['verdict']}", flush=True)
    return 0 if rep["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
