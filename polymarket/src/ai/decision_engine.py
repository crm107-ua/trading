from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.ai.nvidia_client import NimResponse, primary_model_id, robust_chat_completion


ActionType = Literal["quote", "cancel_replace", "hold"]
DecisionSource = Literal["rule", "nim", "nim_low_confidence"]


@dataclass(frozen=True)
class Decision:
    action: ActionType
    reason: str
    confidence: float
    source: DecisionSource = "nim"


def _confidence_min() -> float:
    load_repo_dotenv()
    raw = os.environ.get("NVIDIA_NIM_CONFIDENCE_MIN", "0.55").strip()
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 0.55


def _extract_json(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _market_spread_cents(snapshot: dict[str, Any]) -> float | None:
    bb, ba = snapshot.get("best_bid"), snapshot.get("best_ask")
    if bb is None or ba is None:
        return None
    return (float(ba) - float(bb)) * 100.0


def _spot_move_usd(snapshot: dict[str, Any]) -> float | None:
    spot = snapshot.get("spot")
    last = snapshot.get("last_quote_spot")
    if spot is None or last is None:
        return None
    return abs(float(spot) - float(last))


def rule_guard(snapshot: dict[str, Any]) -> Decision | None:
    """
    Deterministic safety layer — runs before NVIDIA. Returns Decision if NIM must not be called.
    """
    if snapshot.get("best_bid") is None or snapshot.get("best_ask") is None:
        return Decision("hold", "rule_missing_book", 1.0, "rule")

    feed_age = snapshot.get("feed_age_ms")
    stale_ms = float(snapshot.get("kill_switch_feed_stale_ms", 2000))
    if feed_age is not None and float(feed_age) > stale_ms:
        return Decision("hold", "rule_stale_feed", 1.0, "rule")

    time_rem = float(snapshot.get("time_remaining_s", 999))
    if time_rem < 12:
        return Decision("hold", "rule_window_closing", 1.0, "rule")

    inv_usd = abs(float(snapshot.get("inventory_shares", 0)) * float(snapshot.get("spot", 1)))
    max_inv = float(snapshot.get("max_inventory_usdc", 1e9))
    if inv_usd >= max_inv * 0.98:
        return Decision("hold", "rule_inventory_cap", 1.0, "rule")

    move = _spot_move_usd(snapshot)
    requote = float(snapshot.get("requote_spot_move_usd", 25))
    if move is not None and move >= requote:
        return Decision("cancel_replace", "rule_spot_moved", 1.0, "rule")

    spread = _market_spread_cents(snapshot)
    if spread is not None and spread < 1.0:
        return Decision("hold", "rule_tight_market_spread", 1.0, "rule")

    return None


def _build_nim_messages(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    spread = _market_spread_cents(snapshot)
    move = _spot_move_usd(snapshot)
    ctx = {
        "spot_usd": snapshot.get("spot"),
        "strike_usd": snapshot.get("strike"),
        "time_remaining_s": snapshot.get("time_remaining_s"),
        "best_bid": snapshot.get("best_bid"),
        "best_ask": snapshot.get("best_ask"),
        "market_spread_cents": round(spread, 2) if spread is not None else None,
        "last_trade": snapshot.get("last_trade"),
        "proposed_bid": snapshot.get("quote_bid"),
        "proposed_ask": snapshot.get("quote_ask"),
        "quote_size_shares": snapshot.get("quote_size"),
        "inventory_shares": snapshot.get("inventory_shares"),
        "spot_move_since_last_quote_usd": round(move, 2) if move is not None else None,
        "requote_threshold_usd": snapshot.get("requote_spot_move_usd"),
        "feed_age_ms": snapshot.get("feed_age_ms"),
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a risk-averse Polymarket market-maker decision engine.\n"
                "Output ONLY JSON: {\"action\":\"quote|cancel_replace|hold\",\"confidence\":0..1,\"reason\":\"...\"}\n"
                "Never change prices — only choose whether to post, refresh, or pause.\n"
                "Prefer HOLD when uncertain. QUOTE when fair is stable and spread is worth capturing.\n"
                "CANCEL_REPLACE when spot moved materially vs last quote anchor."
            ),
        },
        {
            "role": "user",
            "content": f"Market snapshot:\n{json.dumps(ctx, ensure_ascii=False)}",
        },
    ]


def decide_quote_action(
    *,
    snapshot: dict[str, Any],
    latency_budget_ms: int = 750,
    preferred_models: list[str] | None = None,
    use_cache: bool = True,
) -> tuple[Decision, NimResponse | None]:
    """
    Rule guards first, then NVIDIA NIM for the action. Does NOT change pricing parameters.
    """
    guarded = rule_guard(snapshot)
    if guarded is not None:
        return guarded, None

    messages = _build_nim_messages(snapshot)
    conf_min = _confidence_min()
    try:
        resp = robust_chat_completion(
            messages=messages,
            timeout_ms=min(max(latency_budget_ms, 250), 1500),
            temperature=0.0,
            max_tokens=160,
            preferred_models=preferred_models or [primary_model_id()],
            use_cache=use_cache,
        )
    except Exception:
        return Decision("hold", "nim_error_or_timeout", 0.0, "rule"), None

    data = _extract_json(resp.content) or {}
    action = data.get("action")
    if action not in ("quote", "cancel_replace", "hold"):
        return Decision("hold", "nim_bad_format", 0.0, "rule"), resp
    try:
        conf = float(data.get("confidence", 0.5))
    except Exception:
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    reason = str(data.get("reason") or "nim_decision").strip()[:200]

    if action != "hold" and conf < conf_min:
        return Decision("hold", f"nim_low_confidence:{reason}", conf, "nim_low_confidence"), resp

    return Decision(action=action, reason=reason, confidence=conf, source="nim"), resp
