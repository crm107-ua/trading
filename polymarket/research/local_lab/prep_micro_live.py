#!/usr/bin/env python3
"""
Checklist + ping Relayer para micro-live (~5 EUR).

NO coloca órdenes. NO gasta gas. Solo verifica .env y conectividad.

    python -m polymarket.research.local_lab.prep_micro_live
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

ROOT = Path(__file__).resolve().parents[3]
CFG_DEFAULT = ROOT / "polymarket" / "config" / "maker_demo_5_eur_t4_micro_live.json"


def _filled(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def _mask(v: str, keep: int = 6) -> str:
    v = (v or "").strip()
    if len(v) <= keep * 2:
        return "***"
    return f"{v[:keep]}…{v[-keep:]}"


def check_env() -> dict:
    req = [
        "RELAYER_API_KEY",
        "RELAYER_API_KEY_ADDRESS",
        "POLYMARKET_WALLET_ADDRESS",
    ]
    missing_live = [
        "POLY_PRIVATE_KEY",
        "POLY_CLOB_API_KEY",
        "POLY_CLOB_API_SECRET",
        "POLY_CLOB_API_PASSPHRASE",
    ]
    out = {
        "relayer_ready": all(_filled(k) for k in req),
        "signing_ready": _filled("POLY_PRIVATE_KEY"),
        "clob_ready": all(_filled(k) for k in missing_live[1:]),
        "armed": (os.getenv("POLY_LIVE_ARMED") or "0").strip() == "1",
        "dry_run": (os.getenv("POLY_LIVE_DRY_RUN") or "1").strip() != "0",
        "max_capital": float(os.getenv("POLY_LIVE_MAX_CAPITAL_USDC") or "5"),
        "config": os.getenv("POLY_LIVE_CONFIG") or str(CFG_DEFAULT),
        "present": {},
        "missing_for_real_orders": [],
    }
    for k in req + missing_live + [
        "POLY_LIVE_ARMED",
        "POLY_LIVE_DRY_RUN",
        "POLY_LIVE_MAX_CAPITAL_USDC",
    ]:
        val = (os.getenv(k) or "").strip()
        if "KEY" in k or "SECRET" in k or "PASSPHRASE" in k or "PRIVATE" in k:
            out["present"][k] = _mask(val) if val else "(vacío)"
        else:
            out["present"][k] = val or "(vacío)"
    for k in missing_live:
        if not _filled(k):
            out["missing_for_real_orders"].append(k)
    return out


def ping_relayer() -> dict:
    key = (os.getenv("RELAYER_API_KEY") or "").strip()
    addr = (os.getenv("RELAYER_API_KEY_ADDRESS") or "").strip()
    host = (os.getenv("POLY_RELAYER_HOST") or "https://relayer-v2.polymarket.com").rstrip("/")
    if not key or not addr:
        return {"ok": False, "error": "missing RELAYER_API_KEY / ADDRESS"}
    url = f"{host}/v1/account/transactions/params"
    try:
        r = httpx.get(
            url,
            params={"address": addr, "type": "SAFE"},
            headers={
                "RELAYER_API_KEY": key,
                "RELAYER_API_KEY_ADDRESS": addr,
            },
            timeout=20.0,
        )
        body = None
        try:
            body = r.json()
        except Exception:
            body = (r.text or "")[:300]
        return {
            "ok": r.status_code < 400,
            "status_code": r.status_code,
            "url": url,
            "body": body,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def load_cfg(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_file():
        p = ROOT / path
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    env = check_env()
    cfg_path = env["config"]
    cfg = load_cfg(cfg_path) if Path(cfg_path).is_file() or (ROOT / cfg_path).is_file() else {}
    ping = ping_relayer()

    print("=== POLY MICRO-LIVE PREP (sin órdenes) ===")
    print(json.dumps({"env": env, "relayer_ping": ping, "strategy_cfg_cap": {
        "demo_label": cfg.get("demo_label"),
        "initial_capital_usdc": cfg.get("initial_capital_usdc"),
        "quote_size_shares": cfg.get("quote_size_shares"),
        "max_notional_per_side_usdc": cfg.get("max_notional_per_side_usdc"),
        "max_loss_usdc": cfg.get("max_loss_usdc"),
        "lock_profit_usdc": cfg.get("lock_profit_usdc"),
        "session_kill_net_usdc": cfg.get("session_kill_net_usdc"),
        "live_onchain": cfg.get("live_onchain"),
    }}, indent=2, ensure_ascii=False))

    print("\n--- Checklist ---")
    print(f"[ {'OK' if env['relayer_ready'] else 'NO'} ] Relayer API key + address")
    print(f"[ {'OK' if ping.get('ok') else 'NO'} ] Ping Relayer HTTP")
    print(f"[ {'OK' if env['signing_ready'] else 'NO'} ] POLY_PRIVATE_KEY (firma)")
    print(f"[ {'OK' if env['clob_ready'] else 'NO'} ] Credenciales CLOB (orders)")
    print(f"[ {'OK' if env['dry_run'] else 'ARMED-DRY=0'} ] DRY_RUN={env['dry_run']}")
    print(f"[ {'ARMED' if env['armed'] else 'SAFE'} ] POLY_LIVE_ARMED={env['armed']}")
    print(f"[ CAP ] max capital = {env['max_capital']} USDC/EUR")

    if env["missing_for_real_orders"]:
        print("\nFalta para órdenes reales:")
        for k in env["missing_for_real_orders"]:
            print(f"  - {k}")
        print(
            "\nAún NO se puede ir live completo. Relayer solo = gasless/approvals.\n"
            "Cuando tengas private key + CLOB keys: ponlos en .env, deja\n"
            "POLY_LIVE_ARMED=0 y POLY_LIVE_DRY_RUN=1, y vuelve a correr este script.\n"
            "Solo entonces, si confirmas, se arma micro-live a 5€."
        )
        return 2

    if not env["armed"] or env["dry_run"]:
        print(
            "\nCredenciales mínimas OK, pero el armado sigue en SAFE/DRY.\n"
            "Para dinero real (cuando tú digas): POLY_LIVE_DRY_RUN=0 y POLY_LIVE_ARMED=1."
        )
        return 0

    print("\n*** ARMED + DRY_RUN=0 — listo para el runner live (aún no implementado aquí). ***")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
