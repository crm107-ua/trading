#!/usr/bin/env python3
"""
Definitive Temperature Ladder income system — single production entrypoint.

Unifies strategy certification + DNA alignment + live readiness into one verdict:

  DEFINITIVE_SYSTEM_CERTIFIED  — research gates green (long-term / WR80 / income)
  REAL_INCOME_OPERABLE         — certified + signing + configs aligned
  REAL_INCOME_GO               — operable + geoblock OK + balance + edge open
  BLOCKED_*                    — see blockers list

  # Full certify + status (safe, no orders)
  python3 -m polymarket.research.local_lab.definitive_income_system

  # Re-run research certifications
  python3 -m polymarket.research.local_lab.definitive_income_system --recertify

  # Income loop (real money; allowed region + deposit required)
  POLY_LADDER_REAL_CONFIRM=1 \\
    python3 -m polymarket.research.local_lab.definitive_income_system \\
      --income-loop --auto-execute --i-accept-real-loss YES

  # Real-env readiness (no orders)
  python3 -m polymarket.research.local_lab.real_env_ready --scale high
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.weather_ladder_paper import load_cfg
from polymarket.src.ai.env_loader import load_repo_dotenv

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "definitive_system"

FINAL_CFG = POLY / "config" / "weather_ladder_final_longterm.json"
DEFINITIVE_REAL = POLY / "config" / "weather_ladder_definitive_real.json"
HIGH_INCOME = POLY / "config" / "weather_ladder_high_income.json"
MICRO_REAL = POLY / "config" / "weather_ladder_micro_real.json"
INCOME_WR80 = POLY / "config" / "weather_ladder_income_wr80.json"

SCALE_CONFIGS = {
    "micro": DEFINITIVE_REAL,
    "definitive": DEFINITIVE_REAL,
    "high": HIGH_INCOME,
    "aggressive": HIGH_INCOME,  # same DNA; aggressive sizing via deposit + env
}

REQUIRED_CITIES = {"singapore", "shanghai", "beijing", "hong-kong"}
DNA_KEYS = (
    "max_basket_cost",
    "max_leg_price",
    "require_underdispersion",
    "min_cluster_prob",
)


def _latest_json(dir_path: Path, pattern: str) -> dict[str, Any] | None:
    if not dir_path.is_dir():
        return None
    files = sorted(dir_path.glob(pattern))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def _sleeve_press_only(cfg: dict[str, Any]) -> bool:
    for s in cfg.get("sleeves") or []:
        tiers = [t.get("name") for t in (s.get("tiers") or [])]
        if tiers != ["press_under"]:
            return False
    return bool(cfg.get("sleeves"))


def _cities_norm(cfg: dict[str, Any]) -> set[str]:
    return {str(c).lower().replace(" ", "-") for c in (cfg.get("cities") or [])}


def check_dna_alignment() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []
    configs = {
        "final": FINAL_CFG,
        "definitive_real": DEFINITIVE_REAL,
        "high_income": HIGH_INCOME,
        "micro_real": MICRO_REAL,
        "income_wr80": INCOME_WR80,
    }
    loaded: dict[str, dict[str, Any]] = {}
    for name, path in configs.items():
        ok = path.is_file()
        checks[f"{name}_exists"] = ok
        if not ok:
            notes.append(f"missing {path.name}")
            continue
        loaded[name] = json.loads(path.read_text(encoding="utf-8"))

    final = loaded.get("final") or {}
    lt = final.get("long_term") or {}
    cert = lt.get("certification") or {}
    checks["final_long_term_robust"] = (
        cert.get("verdict") == "LONG_TERM_ROBUST" or lt.get("verdict") == "LONG_TERM_ROBUST"
    )
    checks["final_press_only"] = _sleeve_press_only(final) if final else False
    checks["final_bj_le_050"] = True
    if final:
        by = {s["name"]: s for s in final.get("sleeves") or []}
        bj = by.get("beijing_press") or {}
        checks["final_bj_le_050"] = float(bj.get("max_basket_cost") or 99) <= 0.50 + 1e-12

    for name in ("definitive_real", "high_income", "micro_real", "income_wr80"):
        cfg = loaded.get(name)
        if not cfg:
            continue
        checks[f"{name}_press_only"] = _sleeve_press_only(cfg)
        checks[f"{name}_basket_le_050"] = float(cfg.get("max_basket_cost") or 99) <= 0.50 + 1e-12
        checks[f"{name}_leg_le_039"] = float(cfg.get("max_leg_price") or 99) <= 0.39 + 1e-12
        checks[f"{name}_ud_required"] = bool(cfg.get("require_underdispersion", False))
        cities = _cities_norm(cfg)
        checks[f"{name}_core_cities"] = REQUIRED_CITIES.issubset(cities) or cities == REQUIRED_CITIES

    # Cap discipline for micro sleeves only
    for name in ("definitive_real", "micro_real"):
        cfg = loaded.get(name) or {}
        live = cfg.get("live") or {}
        checks[f"{name}_cap_le_5"] = float(live.get("max_capital_usdc") or 99) <= 5.0 + 1e-12
        checks[f"{name}_max_markets_1"] = int(cfg.get("max_markets_per_run") or 99) <= 1
        checks[f"{name}_no_smoke"] = not bool(cfg.get("smoke_post_when_empty"))
        checks[f"{name}_open_only"] = bool(cfg.get("open_only"))

    # High-income: same DNA, larger cap allowed, still no smoke / open_only / press
    hi = loaded.get("high_income") or {}
    if hi:
        live = hi.get("live") or {}
        checks["high_income_no_smoke"] = not bool(hi.get("smoke_post_when_empty"))
        checks["high_income_open_only"] = bool(hi.get("open_only"))
        checks["high_income_cap_le_100"] = float(live.get("max_capital_usdc") or 99) <= 100.0 + 1e-12
        checks["high_income_flag"] = bool(live.get("high_income"))
        checks["high_income_max_markets_le_2"] = int(hi.get("max_markets_per_run") or 99) <= 2
        checks["high_income_budget_ge_20"] = float(hi.get("budget_per_market_usdc") or 0) >= 20.0

    required = [k for k, v in checks.items()]
    passed = all(checks.values()) if checks else False
    return {
        "passed": passed,
        "checks": checks,
        "required": required,
        "notes": notes,
        "final_overall": (lt.get("overall") if final else None),
    }


def check_research_artifacts(*, recertify: bool = False) -> dict[str, Any]:
    """Load or regenerate long-term / WR80 / income-sim artifacts."""
    if recertify:
        env = {**os.environ, "PYTHONPATH": str(POLY.parent if POLY.name == "polymarket" else POLY)}
        # Workspace root on PYTHONPATH
        root = str(POLY.parent)
        env["PYTHONPATH"] = root
        mods = [
            "polymarket.research.local_lab.long_term_robustness",
            "polymarket.research.local_lab.assure_wr80_income",
            "polymarket.research.local_lab.simulate_real_income",
        ]
        for mod in mods:
            subprocess.run(
                [sys.executable, "-m", mod],
                cwd=root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

    lt = _latest_json(POLY / "data_local" / "local_lab" / "long_term_robust", "long_term_*.json")
    wr = _latest_json(POLY / "data_local" / "local_lab" / "wr80_assurance", "assure_*.json")
    inc = _latest_json(POLY / "data_local" / "local_lab" / "real_income_sim", "sim_*.json")

    # Fallback: embedded certification on final config
    final = json.loads(FINAL_CFG.read_text(encoding="utf-8")) if FINAL_CFG.is_file() else {}
    embedded = (final.get("long_term") or {}).get("certification") or {}

    lt_verdict = None
    if lt:
        best = lt.get("best") if isinstance(lt.get("best"), dict) else {}
        lt_verdict = (
            (lt.get("gate") or {}).get("verdict")
            or (best.get("gate") or {}).get("verdict")
            or lt.get("verdict")
        )
        if lt.get("best_profile") and isinstance(lt.get("gate"), dict):
            lt_verdict = lt["gate"].get("verdict") or lt_verdict
    if not lt_verdict:
        lt_verdict = embedded.get("verdict")

    wr_verdict = (wr or {}).get("verdict") or ((wr or {}).get("gate") or {}).get("verdict")
    inc_verdict = ((inc or {}).get("gate") or {}).get("verdict") or (inc or {}).get("verdict")

    checks = {
        "long_term_robust": lt_verdict == "LONG_TERM_ROBUST",
        "wr80_assured": wr_verdict in ("INCOME_WR80_POINT_ASSURED", "INCOME_WR80_ASSURED"),
        "income_generation_assured": inc_verdict == "INCOME_GENERATION_ASSURED",
    }
    # If wr/income artifacts missing but final DNA is certified long-term, still require them for full certify
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "verdicts": {
            "long_term": lt_verdict,
            "wr80": wr_verdict,
            "income_sim": inc_verdict,
        },
        "artifacts": {
            "long_term": bool(lt) or bool(embedded),
            "wr80": bool(wr),
            "income_sim": bool(inc),
        },
    }


def check_live_operability(cfg: dict[str, Any]) -> dict[str, Any]:
    from polymarket.research.local_lab.weather_ladder_real import evaluate_real_stack

    stack = evaluate_real_stack(cfg)
    bal = (stack.get("wallet") or {}).get("balance_pusd")
    deposit_target = float((cfg.get("live") or {}).get("deposit_target_usdc") or 25.0)
    min_arm = float((cfg.get("live") or {}).get("min_balance_to_arm_usdc") or 2.0)
    checks = {
        "signing_ready": bool((stack.get("checks") or {}).get("signing_ready")),
        "balance_readable": bool((stack.get("checks") or {}).get("balance_readable")),
        "geoblock_ok": bool((stack.get("checks") or {}).get("geoblock_ok")),
        "day_loss_ok": bool((stack.get("checks") or {}).get("day_loss_ok")),
        "balance_gte_micro": (bal or 0) >= max(2.0, min_arm),
        "balance_gte_deposit_target": (bal or 0) >= deposit_target - 1e-9,
        "edge_open": int((stack.get("market_now") or {}).get("accepted_n") or 0) >= 1,
        "env_safe": bool((stack.get("checks") or {}).get("env_starts_safe")),
    }
    operational_blockers = []
    if not checks["geoblock_ok"]:
        operational_blockers.append("geoblock_region")
    if not checks["balance_gte_micro"]:
        operational_blockers.append(f"deposit_needed_min_{min_arm:g}")
    elif not checks["balance_gte_deposit_target"]:
        operational_blockers.append(f"deposit_recommended_to_{deposit_target:g}")
    if not checks["edge_open"]:
        operational_blockers.append("wait_for_champion_basket")
    if not checks["signing_ready"]:
        operational_blockers.append("signing_not_ready")

    return {
        "checks": checks,
        "stack_summary": {
            "balance_pusd": bal,
            "suggested_deposit_to_25": (stack.get("wallet") or {}).get("suggested_deposit_to_25"),
            "suggested_deposit_to_target": (stack.get("wallet") or {}).get("suggested_deposit_to_target"),
            "accepted_n": (stack.get("market_now") or {}).get("accepted_n"),
            "near_miss": (stack.get("market_now") or {}).get("near_miss"),
            "ready_to_arm": stack.get("ready_to_arm"),
            "can_execute_now": stack.get("can_execute_now"),
            "blockers": stack.get("blockers"),
            "geoblock": stack.get("geoblock"),
            "session_limits": stack.get("session_limits"),
            "income_mode": stack.get("income_mode"),
        },
        "operational_blockers": operational_blockers,
        "stack": stack,
    }


def compose_verdict(
    dna: dict[str, Any],
    research: dict[str, Any],
    live: dict[str, Any],
) -> dict[str, Any]:
    certified = bool(dna.get("passed")) and bool(research.get("passed"))
    signing_ok = bool((live.get("checks") or {}).get("signing_ready")) and bool(
        (live.get("checks") or {}).get("balance_readable")
    )
    operable = certified and signing_ok and bool((live.get("checks") or {}).get("env_safe"))
    go = (
        operable
        and bool((live.get("checks") or {}).get("geoblock_ok"))
        and bool((live.get("checks") or {}).get("balance_gte_micro"))
        and bool((live.get("checks") or {}).get("edge_open"))
        and bool((live.get("checks") or {}).get("day_loss_ok"))
    )

    if go:
        verdict = "REAL_INCOME_GO"
    elif operable:
        verdict = "REAL_INCOME_OPERABLE"
    elif certified:
        verdict = "DEFINITIVE_SYSTEM_CERTIFIED"
    else:
        verdict = "DEFINITIVE_NOT_READY"

    return {
        "verdict": verdict,
        "certified": certified,
        "operable": operable,
        "go": go,
        "meaning": {
            "DEFINITIVE_SYSTEM_CERTIFIED": "Estrategia definitiva certificada (research). Falta operatividad live.",
            "REAL_INCOME_OPERABLE": "Sistema listo; falta región permitida y/o depósito y/o edge abierto.",
            "REAL_INCOME_GO": "Puedes ejecutar ingreso real ahora (confirm env + accept loss).",
            "DEFINITIVE_NOT_READY": "DNA o certificaciones incompletas — no operar real.",
        }.get(verdict, ""),
    }


def run_system(
    *,
    recertify: bool = False,
    skip_live: bool = False,
    scale: str = "micro",
) -> dict[str, Any]:
    load_repo_dotenv(override=True)
    dna = check_dna_alignment()
    research = check_research_artifacts(recertify=recertify)

    cfg_path = SCALE_CONFIGS.get(scale, DEFINITIVE_REAL)
    if not cfg_path.is_file():
        cfg_path = DEFINITIVE_REAL if DEFINITIVE_REAL.is_file() else MICRO_REAL
    cfg = load_cfg(cfg_path)
    if scale == "aggressive":
        # Same DNA, larger notional for aggressive deposit
        cfg = dict(cfg)
        cfg["budget_per_market_usdc"] = 50.0
        cfg["income_mode"] = "aggressive"
        live = dict(cfg.get("live") or {})
        live["max_capital_usdc"] = 100.0
        live["deposit_target_usdc"] = 200.0
        live["min_balance_to_arm_usdc"] = 50.0
        live["high_income"] = True
        cfg["live"] = live
        for s in cfg.get("sleeves") or []:
            s["budget_per_market_usdc"] = 50.0

    projections = None
    try:
        from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
        from polymarket.research.local_lab.high_income_project import project

        cases = json.loads(
            (POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json").read_text(
                encoding="utf-8"
            )
        )
        projections = project(take_income_wr80(cases))
    except Exception as exc:  # noqa: BLE001
        projections = {"error": f"{type(exc).__name__}: {exc}"}

    if skip_live:
        live = {
            "checks": {},
            "stack_summary": {},
            "operational_blockers": ["live_skipped"],
            "stack": {},
        }
    else:
        live = check_live_operability(cfg)

    composed = compose_verdict(dna, research, live)
    income_cmd = (
        ("POLY_LADDER_HIGH_INCOME=1 " if scale in ("high", "aggressive") else "")
        + "POLY_LADDER_REAL_CONFIRM=1 "
        "python3 -m polymarket.research.local_lab.definitive_income_system "
        f"--scale {scale} --income-loop --auto-execute --i-accept-real-loss YES "
        "--rounds 40 --interval 180"
    )

    want_name = {
        "micro": "micro",
        "definitive": "micro",
        "high": "high",
        "aggressive": "aggressive",
    }.get(scale, "micro")
    scale_row = None
    for s in (projections or {}).get("scales") or []:
        if s.get("name") == want_name:
            scale_row = s
            break

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "system": "temperature_ladder_definitive",
        "scale": scale,
        "config_real": str(cfg_path.name),
        "config_research": FINAL_CFG.name,
        "dna": {k: dna[k] for k in ("passed", "checks", "notes", "final_overall")},
        "research": research,
        "live": {
            "checks": live.get("checks"),
            "summary": live.get("stack_summary"),
            "operational_blockers": live.get("operational_blockers"),
        },
        "projections": projections,
        "headline_income": scale_row,
        **composed,
        "how_to_earn": {
            "1_deposit": (
                "High: deposita ≥$100 (aggressive ≥$200)."
                if scale in ("high", "aggressive")
                else "Deposita ≥25 USDC (mínimo técnico $2)."
            ),
            "2_region": "Corre desde región permitida por Polymarket (no geoblock US).",
            "3_command": income_cmd,
            "4_hold": "Compra basket press-only FAK y hold hasta resolución.",
            "5_more_pnl": "Más ganancia = más tamaño en el MISMO edge; no aflojar baskets.",
        },
        "safety": {
            "session_cap_usdc": float((cfg.get("live") or {}).get("max_capital_usdc") or 5),
            "press_only": True,
            "max_basket": 0.50,
            "abort_partial": True,
            "restores_safe_after": True,
            "requires_double_confirm": True,
            "high_income_env_required_over_5": scale in ("high", "aggressive"),
        },
    }
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="Definitive ladder income system")
    p.add_argument("--recertify", action="store_true", help="Re-run research certification suites")
    p.add_argument("--skip-live", action="store_true", help="Skip CLOB/geoblock probes")
    p.add_argument(
        "--scale",
        choices=sorted(SCALE_CONFIGS.keys()),
        default="micro",
        help="micro/definitive=$5; high/aggressive=larger $/trade same DNA",
    )
    p.add_argument("--income-loop", action="store_true", help="Hand off to ladder_income_loop")
    p.add_argument("--auto-execute", action="store_true")
    p.add_argument("--i-accept-real-loss", default="")
    p.add_argument("--rounds", type=int, default=40)
    p.add_argument("--interval", type=float, default=180.0)
    args = p.parse_args()

    out_dir = OUT / datetime.now(timezone.utc).strftime("sys_%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    report = run_system(
        recertify=args.recertify,
        skip_live=args.skip_live or args.income_loop,
        scale=args.scale,
    )
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = {
        "verdict": report["verdict"],
        "meaning": report["meaning"],
        "scale": report["scale"],
        "certified": report["certified"],
        "operable": report["operable"],
        "go": report["go"],
        "headline_income": report.get("headline_income"),
        "research_verdicts": report["research"]["verdicts"],
        "dna_passed": report["dna"]["passed"],
        "live_summary": report["live"]["summary"],
        "operational_blockers": report["live"]["operational_blockers"],
        "how_to_earn": report["how_to_earn"],
        "report": str(out_dir / "report.json"),
    }
    print(json.dumps(summary, indent=2), flush=True)

    if args.income_loop:
        if not report["certified"]:
            print("Refusing income-loop: strategy not certified.", flush=True)
            return 2
        if not report["dna"]["passed"]:
            print("Refusing income-loop: DNA misaligned.", flush=True)
            return 2
        if args.scale in ("high", "aggressive"):
            if (os.getenv("POLY_LADDER_HIGH_INCOME") or "").strip() != "1":
                raise SystemExit("Refusing high-income loop without POLY_LADDER_HIGH_INCOME=1")
        from polymarket.research.local_lab.ladder_income_loop import run_loop

        cfg = SCALE_CONFIGS.get(args.scale, DEFINITIVE_REAL)
        if not cfg.is_file():
            cfg = MICRO_REAL
        if args.auto_execute and args.i_accept_real_loss.strip().upper() != "YES":
            raise SystemExit("Refusing --auto-execute without --i-accept-real-loss YES")
        if args.auto_execute and (os.getenv("POLY_LADDER_REAL_CONFIRM") or "").strip() != "1":
            raise SystemExit("Refusing --auto-execute without POLY_LADDER_REAL_CONFIRM=1")
        loop_rep = run_loop(
            config_path=cfg,
            rounds=args.rounds,
            interval_s=args.interval,
            auto_execute=args.auto_execute,
            accept_loss=args.i_accept_real_loss,
        )
        (out_dir / "income_loop.json").write_text(json.dumps(loop_rep, indent=2), encoding="utf-8")
        print(f"income_loop_verdict={loop_rep.get('verdict')}", flush=True)
        return 0 if loop_rep.get("verdict") in (
            "INCOME_POSTED",
            "EDGE_READY_MANUAL",
            "NO_EDGE_YET",
            "BLOCKED_GEOBLOCK",
        ) else 2

    return 0 if report["certified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
