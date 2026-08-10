#!/usr/bin/env python3
"""
Multi-bankroll watch helpers ($live / $100 / $200) — sim only, no posts.

Used by progress_watch when DNA edge appears: sizes what-if for each wallet
and returns Telegram-ready fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.wallet_take_reality_sim import what_if_single_take

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "vps_runs"

# Hypothetical high bankrolls (same DNA; larger session/budget for sizing)
HIGH_SESSION_CAP = 50.0
HIGH_BUDGET = 25.0
MICRO_SESSION_CAP = 5.0
MICRO_BUDGET = 3.0


def _caps_for(balance: float) -> tuple[float, float]:
    if balance >= 50:
        return HIGH_SESSION_CAP, HIGH_BUDGET
    return MICRO_SESSION_CAP, MICRO_BUDGET


def multi_bankroll_what_if(
    *,
    live_balance: float,
    extra: list[float] | None = None,
) -> dict[str, Any]:
    balances = [float(live_balance)]
    for b in extra or [100.0, 200.0]:
        if abs(float(b) - float(live_balance)) > 1e-6:
            balances.append(float(b))

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    raw = take_income_wr80(cases)
    rows: list[dict[str, Any]] = []
    any_sizeable = False
    for bal in balances:
        sess, bud = _caps_for(bal)
        w = what_if_single_take(raw, balance=bal, session_cap=sess, budget_cfg=bud)
        paths = w.get("paths") or {}
        win = paths.get("clean_win") or {}
        miss = paths.get("full_miss") or {}
        sizeable = bool(w.get("executable_now"))
        any_sizeable = any_sizeable or sizeable
        rows.append(
            {
                "balance_usdc": bal,
                "session_cap": sess,
                "budget": bud,
                "sizeable": sizeable,
                "notional": w.get("notional_usdc"),
                "block_reason": w.get("block_reason"),
                "win_pnl": win.get("pnl"),
                "win_equity": win.get("equity_after"),
                "miss_pnl": miss.get("pnl"),
                "miss_equity": miss.get("equity_after"),
            }
        )

    report = {
        "any_sizeable": any_sizeable,
        "n_bankrolls": len(rows),
        "rows": rows,
        "note": "WATCH_ONLY sim — no orders. DNA edge uses live books; PnL paths are hypothetical sizing.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "MULTI_BANKROLL_EDGE.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def telegram_fields(report: dict[str, Any], *, round_id: Any = None, accepted_n: Any = None) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "modo": "WATCH_ONLY x3 ($live/$100/$200)",
        "acción": "NO se postea — solo aviso",
    }
    if round_id is not None:
        fields["round"] = round_id
    if accepted_n is not None:
        fields["accepted_n"] = accepted_n
    for row in report.get("rows") or []:
        bal = row["balance_usdc"]
        if row.get("sizeable"):
            fields[f"${bal:g}"] = (
                f"SIZEABLE notional={row.get('notional')} "
                f"win→{row.get('win_equity')} miss→{row.get('miss_equity')}"
            )
        else:
            fields[f"${bal:g}"] = f"NO sizeable ({row.get('block_reason') or 'n/a'})"
    fields["any_sizeable"] = report.get("any_sizeable")
    return fields


def format_plain(report: dict[str, Any]) -> str:
    lines = ["MULTI-BANKROLL EDGE (WATCH ONLY)"]
    for row in report.get("rows") or []:
        bal = row["balance_usdc"]
        if row.get("sizeable"):
            lines.append(
                f"${bal:g}: SIZEABLE ~{row.get('notional')} | "
                f"win eq {row.get('win_equity')} | miss eq {row.get('miss_equity')}"
            )
        else:
            lines.append(f"${bal:g}: no sizeable")
    return "\n".join(lines)
