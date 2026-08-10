#!/usr/bin/env python3
"""
Temperature Ladder — micro REAL money runner.

Default is PREFLIGHT only (no orders). To spend real capital you must pass
ALL of:
  1) --execute-real
  2) --i-accept-real-loss YES
  3) env POLY_LADDER_REAL_CONFIRM=1
  4) geoblock OK, balance OK, champion take present
  5) session cap ≤ $5

After any execute attempt the process restores SAFE (ARMED=0, DRY_RUN=1).

  # See how real would look (recommended first):
  python3 -m polymarket.research.local_lab.weather_ladder_real

  # Actually post (money at risk):
  POLY_LADDER_REAL_CONFIRM=1 \\
    python3 -m polymarket.research.local_lab.weather_ladder_real \\
      --execute-real --i-accept-real-loss YES
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.weather_ladder_live import (
    prepare_candidates,
    run_book_sim,
)
from polymarket.research.local_lab.weather_ladder_paper import load_cfg
from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.execution.clob_live import ClobLiveClient, read_gates
from polymarket.src.execution.live_policy import (
    check_geoblock,
    day_loss_breached,
    geoblock_blocks_real,
    record_session_pnl,
)

POLY = Path(__file__).resolve().parents[2]
DEFAULT_CFG = POLY / "config" / "weather_ladder_definitive_real.json"
# Definitive real sleeve = final long-term DNA; micro_real kept as alias path.
OUT = POLY / "data_local" / "local_lab" / "weather_ladder_real"
MAX_SESSION_CAP_MICRO = 5.0
MAX_SESSION_CAP_HIGH = 100.0  # hard ceiling even in high-income mode
STRATEGY_ID = "temperature_ladder_definitive"


def _session_cap(cfg: dict[str, Any]) -> float:
    """Micro default $5; high-income may raise up to hard ceiling with env flag."""
    live = cfg.get("live") or {}
    wanted = float(live.get("max_capital_usdc") or cfg.get("initial_capital_usdc") or 5.0)
    high = bool(live.get("high_income")) or wanted > MAX_SESSION_CAP_MICRO + 1e-9
    if high:
        if (os.getenv("POLY_LADDER_HIGH_INCOME") or "").strip() != "1":
            # Fall back to micro until explicitly armed for size
            return min(MAX_SESSION_CAP_MICRO, wanted)
        return min(MAX_SESSION_CAP_HIGH, max(MAX_SESSION_CAP_MICRO, wanted))
    return min(MAX_SESSION_CAP_MICRO, wanted)


def _restore_safe() -> None:
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"


def _arm_real(*, max_capital: float) -> dict[str, str]:
    prev = {
        "POLY_LIVE_ARMED": os.environ.get("POLY_LIVE_ARMED", ""),
        "POLY_LIVE_DRY_RUN": os.environ.get("POLY_LIVE_DRY_RUN", ""),
        "POLY_LIVE_MAX_CAPITAL_USDC": os.environ.get("POLY_LIVE_MAX_CAPITAL_USDC", ""),
    }
    os.environ["POLY_LIVE_ARMED"] = "1"
    os.environ["POLY_LIVE_DRY_RUN"] = "0"
    os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = str(float(max_capital))
    return prev


def _restore_prev(prev: dict[str, str]) -> None:
    for k, v in prev.items():
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _restore_safe()


def evaluate_real_stack(cfg: dict[str, Any]) -> dict[str, Any]:
    """Full picture of how real money sits right now (no posts)."""
    load_repo_dotenv(override=True)
    max_cap = _session_cap(cfg)
    min_bal = float((cfg.get("live") or {}).get("min_balance_to_arm_usdc") or 2.0)
    bal_gate = max(2.0, min(min_bal, max_cap))
    gates0 = read_gates()
    cli = ClobLiveClient()
    bal = None
    bal_err = None
    try:
        cli.connect(derive_api_creds=True)
        bal = float(cli.balance_collateral_usdc())
    except Exception as exc:  # noqa: BLE001
        bal_err = f"{type(exc).__name__}: {exc}"

    geo = check_geoblock()
    geo_blocked, geo_msg = geoblock_blocks_real()
    pack = prepare_candidates(cfg)
    accepted = pack["accepted"]
    notional = sum(float(c.get("notional_usdc") or 0) for c in accepted)
    eff_cap = max_cap if bal is None else min(max_cap, round(bal * 0.95, 2))

    high_env = (os.getenv("POLY_LADDER_HIGH_INCOME") or "").strip() == "1"
    high_wanted = bool((cfg.get("live") or {}).get("high_income")) or float(
        (cfg.get("live") or {}).get("max_capital_usdc") or 0
    ) > MAX_SESSION_CAP_MICRO + 1e-9
    max_markets_limit = 2 if high_wanted else 1

    checks = {
        "env_starts_safe": (not gates0.armed) and gates0.dry_run,
        "signing_ready": gates0.signing_ready or bal is not None,
        "balance_readable": bal is not None,
        "balance_gte_2": (bal or 0) >= 2.0,
        "balance_gte_min_arm": (bal or 0) >= bal_gate - 1e-9,
        "geoblock_ok": not geo_blocked,
        "day_loss_ok": not day_loss_breached(),
        "champion_take_available": len(accepted) >= 1,
        "notional_fits_cap": notional <= eff_cap + 1e-9 if accepted else True,
        "notional_fits_balance": (bal is None) or (notional <= (bal or 0) + 1e-9),
        "smoke_disabled": not bool(cfg.get("smoke_post_when_empty")),
        "max_markets_ok": int(cfg.get("max_markets_per_run", 99)) <= max_markets_limit,
        "session_cap_ok": max_cap
        <= ((MAX_SESSION_CAP_HIGH if high_env else MAX_SESSION_CAP_MICRO) + 1e-9),
        "high_income_env_if_needed": (not high_wanted)
        or high_env
        or max_cap <= MAX_SESSION_CAP_MICRO + 1e-9,
    }
    confirm_env = (os.getenv("POLY_LADDER_REAL_CONFIRM") or "").strip() == "1"

    ready_keys = (
        "signing_ready",
        "balance_readable",
        "balance_gte_2",
        "balance_gte_min_arm",
        "geoblock_ok",
        "day_loss_ok",
        "champion_take_available",
        "notional_fits_cap",
        "notional_fits_balance",
        "smoke_disabled",
        "max_markets_ok",
        "session_cap_ok",
        "high_income_env_if_needed",
    )
    ready_to_arm = all(checks[k] for k in ready_keys)

    deposit_target = float((cfg.get("live") or {}).get("deposit_target_usdc") or 25.0)
    deposit_needed = None
    if bal is not None and bal < deposit_target:
        deposit_needed = round(deposit_target - bal, 2)

    return {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": cfg.get("strategy") or STRATEGY_ID,
        "config_demo": cfg.get("demo_label"),
        "income_mode": cfg.get("income_mode") or ("high" if high_wanted else "micro"),
        "wallet": {
            "eoa": gates0.eoa,
            "funder": gates0.funder,
            "balance_pusd": round(bal, 4) if bal is not None else None,
            "balance_error": bal_err,
            "suggested_deposit_to_25": deposit_needed if deposit_target <= 25 else None,
            "suggested_deposit_to_target": deposit_needed,
            "deposit_target_usdc": deposit_target,
        },
        "session_limits": {
            "max_capital_usdc": max_cap,
            "effective_cap_usdc": eff_cap,
            "budget_per_market_usdc": cfg.get("budget_per_market_usdc"),
            "max_markets": cfg.get("max_markets_per_run"),
            "hold_to_resolution": bool((cfg.get("live") or {}).get("hold_to_resolution", True)),
            "high_income_env": high_env,
        },
        "market_now": {
            "events_open": pack["events_open"],
            "accepted_n": len(accepted),
            "accepted": [
                {
                    "slug": c["slug"],
                    "city": c["city"],
                    "day": c["day"],
                    "tier": c.get("tier"),
                    "basket_cost": c.get("basket_cost"),
                    "basket_ev": c.get("basket_ev"),
                    "notional_usdc": c.get("notional_usdc"),
                    "legs": [
                        {"name": l["name"], "price": l["price"], "shares": l["shares"], "dollars": l["dollars"]}
                        for l in c.get("legs") or []
                    ],
                }
                for c in accepted
            ],
            "near_miss": pack["near_miss"],
            "notional_total_usdc": round(notional, 4),
        },
        "geoblock": {
            "blocked": geo.blocked,
            "country": geo.country,
            "region": geo.region,
            "ok_to_trade": geo.ok_to_trade,
            "message": geo_msg,
        },
        "checks": checks,
        "confirm_env_POLY_LADDER_REAL_CONFIRM": confirm_env,
        "ready_to_arm": ready_to_arm,
        "can_execute_now": ready_to_arm and confirm_env and len(accepted) >= 1,
        "blockers": [k for k, v in checks.items() if not v]
        + ([] if confirm_env else ["missing_POLY_LADDER_REAL_CONFIRM=1"])
        + ([] if accepted else ["no_champion_take_right_now"])
        + (
            []
            if (not high_wanted or high_env or max_cap <= MAX_SESSION_CAP_MICRO)
            else ["missing_POLY_LADDER_HIGH_INCOME=1"]
        ),
        "how_it_works": [
            "1. Deposita según escala: micro≥$25 · high≥$100 · aggressive≥$200.",
            "2. Más ingreso = más $ por el MISMO basket press (no baskets peores).",
            "3. High-income real: POLY_LADDER_HIGH_INCOME=1 + POLY_LADDER_REAL_CONFIRM=1.",
            "4. Compra FAK 3 piernas YES; hold hasta resolución.",
            "5. Cap sesión según config (micro $5 / high hasta $50–100); vuelve SAFE.",
            "6. Entrypoint: definitive_income_system --scale high",
        ],
        "commands": {
            "system_status": "python3 -m polymarket.research.local_lab.definitive_income_system --scale high",
            "projections": "python3 -m polymarket.research.local_lab.high_income_project",
            "preflight": (
                "python3 -m polymarket.research.local_lab.weather_ladder_real "
                "--config polymarket/config/weather_ladder_high_income.json"
            ),
            "income_loop_high": (
                "POLY_LADDER_HIGH_INCOME=1 POLY_LADDER_REAL_CONFIRM=1 "
                "python3 -m polymarket.research.local_lab.definitive_income_system "
                "--scale high --income-loop --auto-execute --i-accept-real-loss YES "
                "--rounds 40 --interval 180"
            ),
        },
    }


def execute_real(
    cfg: dict[str, Any],
    *,
    accept_loss: str,
    session_id: str,
) -> dict[str, Any]:
    if accept_loss.strip().upper() != "YES":
        raise RuntimeError("Refusing: --i-accept-real-loss must be exactly YES")
    if (os.getenv("POLY_LADDER_REAL_CONFIRM") or "").strip() != "1":
        raise RuntimeError("Refusing: set POLY_LADDER_REAL_CONFIRM=1 in the environment")

    stack = evaluate_real_stack(cfg)
    if not stack["ready_to_arm"]:
        return {
            "executed": False,
            "reason": "not_ready",
            "blockers": stack["blockers"],
            "stack": stack,
        }
    if not stack["market_now"]["accepted"]:
        return {
            "executed": False,
            "reason": "no_champion_take",
            "stack": stack,
        }

    max_cap = float(stack["session_limits"]["effective_cap_usdc"])
    prev = _arm_real(max_capital=max_cap)
    t0 = time.perf_counter()
    posts: list[dict[str, Any]] = []
    aborted: list[dict[str, Any]] = []
    try:
        gates = read_gates()
        if gates.dry_run or not gates.armed:
            raise RuntimeError("Failed to arm REAL env (DRY_RUN must be 0, ARMED=1)")
        cli = ClobLiveClient()
        cli.connect(derive_api_creds=True)
        bal = cli.balance_collateral_usdc()
        cli.assert_can_trade(capital=max_cap, allow_dry=False)

        order_type = str(cfg.get("order_type") or "FAK")
        # Only first accepted basket (max_markets=1)
        c = stack["market_now"]["accepted"][0]
        # Re-prepare fresh from live books
        pack = prepare_candidates(cfg)
        if not pack["accepted"]:
            return {
                "executed": False,
                "reason": "edge_vanished_before_post",
                "stack": stack,
                "elapsed_s": round(time.perf_counter() - t0, 2),
            }
        c = pack["accepted"][0]
        if float(c["notional_usdc"]) > bal + 1e-9:
            return {
                "executed": False,
                "reason": "insufficient_balance_at_post",
                "balance": bal,
                "notional": c["notional_usdc"],
            }
        # DNA revalidation at post time (slip can inflate basket).
        max_b = float(cfg.get("max_basket_cost") or 0.50)
        post_b = cfg.get("post_max_basket_cost")
        lim = float(post_b) if post_b is not None else max_b + 0.02
        if float(c.get("basket_cost") or 99) > lim + 1e-12:
            return {
                "executed": False,
                "reason": "basket_above_dna_at_post",
                "basket_cost": c.get("basket_cost"),
                "limit": lim,
            }
        if bool(cfg.get("require_underdispersion", True)) and not c.get("underdispersed", True):
            return {"executed": False, "reason": "not_underdispersed_at_post"}
        max_leg = float(cfg.get("max_leg_price") or 0.39)
        for leg in c["legs"]:
            if float(leg.get("price") or 99) > max_leg + 1e-12:
                return {
                    "executed": False,
                    "reason": "leg_above_dna_at_post",
                    "leg": leg.get("name"),
                    "price": leg.get("price"),
                    "max_leg": max_leg,
                }

        basket_posts: list[dict[str, Any]] = []
        ok = True
        for leg in c["legs"]:
            try:
                resp = cli.place_aggressive(
                    token_id=str(leg["token_id"]),
                    side="BUY",
                    price=float(leg["price"]),
                    size=float(leg["shares"]),
                    order_type=order_type,
                )
                row = {
                    "slug": c["slug"],
                    "bucket": leg["name"],
                    "status": resp.get("status"),
                    "would_post": resp.get("would_post"),
                    "orderID": resp.get("orderID"),
                    "response": resp.get("response"),
                }
                basket_posts.append(row)
                if resp.get("status") != "LIVE":
                    ok = False
            except Exception as exc:  # noqa: BLE001
                ok = False
                basket_posts.append(
                    {
                        "slug": c["slug"],
                        "bucket": leg["name"],
                        "status": "ERROR",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        if ok:
            posts = basket_posts
            # Day pnl unknown until resolution — record 0 mark, inventory held
            record_session_pnl(0.0)
        else:
            aborted = basket_posts
            try:
                cli.cancel_all()
            except Exception:
                pass

        return {
            "executed": ok,
            "session_id": session_id,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "onchain": True,
            "slug": c["slug"],
            "city": c["city"],
            "notional_usdc": c["notional_usdc"],
            "posts": posts,
            "aborted": aborted,
            "balance_before": round(bal, 4),
            "hold_to_resolution": True,
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "verdict": "REAL_POSTED" if ok else "REAL_ABORT_PARTIAL",
            "note": "Positions held to resolution; redeem/claim separately if needed.",
        }
    finally:
        _restore_prev(prev)


def main() -> int:
    p = argparse.ArgumentParser(description="Ladder micro REAL (preflight default)")
    p.add_argument("--config", default=str(DEFAULT_CFG))
    p.add_argument("--execute-real", action="store_true")
    p.add_argument("--i-accept-real-loss", default="")
    p.add_argument("--session-id", default=None)
    args = p.parse_args()

    load_repo_dotenv(override=True)
    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        cfg_path = POLY / args.config
    cfg = load_cfg(cfg_path)
    sid = args.session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = OUT / f"session_{sid}"
    out_dir.mkdir(parents=True, exist_ok=True)

    stack = evaluate_real_stack(cfg)
    # Always also snapshot book_sim for audit
    stack["book_sim"] = {
        k: run_book_sim(cfg, session_id=f"{sid}_book")[k]
        for k in ("accepted_n", "notional_total_usdc", "near_miss", "events_open")
    }

    report: dict[str, Any] = {
        "mode": "execute" if args.execute_real else "preflight",
        "session_id": sid,
        "stack": stack,
    }

    if args.execute_real:
        print("=== LADDER REAL EXECUTE (money at risk) ===", flush=True)
        result = execute_real(cfg, accept_loss=args.i_accept_real_loss, session_id=sid)
        report["result"] = result
    else:
        print("=== LADDER REAL PREFLIGHT (no orders) ===", flush=True)

    g = read_gates()
    report["safe_after"] = {"armed": g.armed, "dry_run": g.dry_run}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Human summary
    w = stack["wallet"]
    m = stack["market_now"]
    print(
        json.dumps(
            {
                "balance_pusd": w.get("balance_pusd"),
                "suggested_deposit_to_25": w.get("suggested_deposit_to_25"),
                "session_cap": stack["session_limits"],
                "accepted_n": m["accepted_n"],
                "near_miss": m["near_miss"],
                "ready_to_arm": stack["ready_to_arm"],
                "can_execute_now": stack["can_execute_now"],
                "blockers": stack["blockers"],
                "how_it_works": stack["how_it_works"],
                "commands": stack["commands"],
                "safe_after": report["safe_after"],
                "execute_result": report.get("result", {}).get("verdict")
                if args.execute_real
                else None,
            },
            indent=2,
        )
    )
    print(f"report -> {out_dir / 'report.json'}", flush=True)

    if args.execute_real:
        return 0 if report.get("result", {}).get("executed") else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
