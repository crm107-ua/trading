from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.ai.nvidia_client import NimResponse, primary_model_id, robust_chat_completion


ActionType = Literal["quote", "cancel_replace", "hold", "flatten"]
DecisionSource = Literal["rule", "nim", "nim_low_confidence"]


def _nim_mode() -> str:
    load_repo_dotenv()
    return os.environ.get("NVIDIA_NIM_MODE", "fast").strip().lower()


def fast_path_enabled() -> bool:
    """fast = solo reglas; hybrid/full pueden llamar NIM."""
    return _nim_mode() == "fast"


def hybrid_path_enabled() -> bool:
    return _nim_mode() == "hybrid"


def profit_assist_enabled() -> bool:
    """Usa NIM en más bandas de edge + salidas con inventario (maximizar €)."""
    load_repo_dotenv()
    return os.environ.get("NVIDIA_NIM_PROFIT_ASSIST", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _strong_edge_mult() -> float:
    """Umbral rule_strong_edge. Más alto → más llamadas NIM en hybrid/assist."""
    load_repo_dotenv()
    raw = os.environ.get("NVIDIA_NIM_STRONG_EDGE_MULT", "").strip()
    if not raw:
        return 1.7 if profit_assist_enabled() else 1.25
    try:
        return max(1.05, min(3.0, float(raw)))
    except ValueError:
        return 1.25


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

    inv_usd = abs(float(snapshot.get("inventory_shares", 0)) * float(snapshot.get("mark_price", 0.5)))
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
                "If safety rules already passed and spread is worth capturing, action MUST be \"quote\".\n"
                "Use HOLD only when feed is dubious, spread is too tight, or spot is unstable.\n"
                "CANCEL_REPLACE when spot moved materially vs last quote anchor.\n"
                "action and reason must agree (do not say worth capturing with action hold)."
            ),
        },
        {
            "role": "user",
            "content": f"Market snapshot:\n{json.dumps(ctx, ensure_ascii=False)}",
        },
    ]


def _coerce_action(action: str, reason: str, conf: float, conf_min: float) -> ActionType:
    """Align action with reason when model output is internally inconsistent."""
    rl = reason.lower()
    if action == "hold" and conf >= conf_min:
        if any(p in rl for p in ("worth capturing", "post quote", "stable spread", "should quote")):
            return "quote"
    return action  # type: ignore[return-value]


def decide_quote_action(
    *,
    snapshot: dict[str, Any],
    latency_budget_ms: int = 3000,
    preferred_models: list[str] | None = None,
    use_cache: bool = True,
) -> tuple[Decision, NimResponse | None]:
    """
    Rule guards first, then:
      fast    → quote if spread ok (no API)
      hybrid  → strong edge quote / weak hold / ambiguous → NVIDIA NIM
      full    → always NIM after guards
    Does NOT change pricing parameters.
    """
    guarded = rule_guard(snapshot)
    if guarded is not None:
        return guarded, None

    spread = _market_spread_cents(snapshot)
    min_cents = float(snapshot.get("fast_path_min_spread_cents", 1.0))
    edge_abs = snapshot.get("edge_abs")
    min_edge = float(snapshot.get("min_edge", 0.03))

    if fast_path_enabled():
        if spread is not None and spread >= min_cents:
            return Decision("quote", "rule_fast_path", 1.0, "rule"), None
        return Decision("hold", "rule_fast_tight_spread", 1.0, "rule"), None

    if hybrid_path_enabled():
        strong = _strong_edge_mult()
        if edge_abs is not None:
            if float(edge_abs) >= min_edge * strong and spread is not None and spread >= min_cents:
                return Decision("quote", "rule_strong_edge", 1.0, "rule"), None
            if float(edge_abs) < min_edge * 0.45:
                return Decision("hold", "rule_weak_edge", 1.0, "rule"), None
        # ambiguous / medium edge → fall through to NIM (más ancho si STRONG_EDGE_MULT↑)

    messages = _build_nim_messages(snapshot)
    conf_min = _confidence_min()
    try:
        resp = robust_chat_completion(
            messages=messages,
            timeout_ms=min(max(latency_budget_ms, 500), 4000),
            temperature=0.0,
            max_tokens=120,
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
    action = _coerce_action(str(action), reason, conf, conf_min)

    if action != "hold" and conf < conf_min:
        return Decision("hold", f"nim_low_confidence:{reason}", conf, "nim_low_confidence"), resp

    return Decision(action=action, reason=reason, confidence=conf, source="nim"), resp


def _build_exit_messages(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    ctx = {
        "inventory_shares": snapshot.get("inventory_shares"),
        "avg_entry": snapshot.get("avg_entry"),
        "mark_mid": snapshot.get("mark_price"),
        "fair_up": snapshot.get("fair_up"),
        "unrealized_pnl_usdc": snapshot.get("unrealized_pnl_usdc"),
        "time_remaining_s": snapshot.get("time_remaining_s"),
        "spot_usd": snapshot.get("spot"),
        "best_bid": snapshot.get("best_bid"),
        "best_ask": snapshot.get("best_ask"),
    }
    return [
        {
            "role": "system",
            "content": (
                "You manage an open Polymarket maker inventory to MAXIMIZE session PnL.\n"
                "Output ONLY JSON: "
                '{"action":"hold|flatten","confidence":0..1,"reason":"..."}\n'
                "HOLD = let take-profit / fair edge continue working.\n"
                "FLATTEN = exit now at mid (cut loser early OR lock a win if edge faded).\n"
                "Prefer FLATTEN if unrealized is red and fair no longer favors the position.\n"
                "Prefer HOLD if unrealized is green/flat and fair still supports the side."
            ),
        },
        {
            "role": "user",
            "content": f"Open position snapshot:\n{json.dumps(ctx, ensure_ascii=False)}",
        },
    ]


def _rule_profit_exit(snapshot: dict[str, Any]) -> Decision | None:
    """Corta perdedores rápido / bloquea hold tóxico sin esperar al LLM."""
    inv = float(snapshot.get("inventory_shares") or 0)
    if abs(inv) < 1e-9:
        return None
    unreal = float(snapshot.get("unrealized_pnl_usdc") or 0)
    fair = float(snapshot.get("fair_up") or 0.5)
    mid = float(snapshot.get("mark_price") or 0.5)
    avg = float(snapshot.get("avg_entry") or mid)
    t_rem = snapshot.get("time_remaining_s")
    # Rojo + fair en contra → flatten ya
    if inv > 0 and unreal <= -0.25 and fair < mid - 0.005:
        return Decision("flatten", "rule_cut_red_fade", 1.0, "rule")
    if inv < 0 and unreal <= -0.25 and fair > mid + 0.005:
        return Decision("flatten", "rule_cut_red_fade", 1.0, "rule")
    # Fair cruzó el entry en contra
    if inv > 0 and fair <= avg - 0.025:
        return Decision("flatten", "rule_fair_against", 1.0, "rule")
    if inv < 0 and fair >= avg + 0.025:
        return Decision("flatten", "rule_fair_against", 1.0, "rule")
    # Ventana muriendo en rojo → no esperar resolución
    if t_rem is not None and float(t_rem) <= 55 and unreal < -0.05:
        return Decision("flatten", "rule_late_cut", 1.0, "rule")
    return None


def decide_inventory_exit(
    *,
    snapshot: dict[str, Any],
    latency_budget_ms: int = 2500,
) -> tuple[Decision, NimResponse | None]:
    """
    NIM assist for open inventory: hold vs flatten mid.
    Only used when NVIDIA_NIM_PROFIT_ASSIST is on (or mode=full).
    """
    if not profit_assist_enabled() and _nim_mode() != "full":
        return Decision("hold", "rule_exit_assist_off", 1.0, "rule"), None
    if abs(float(snapshot.get("inventory_shares") or 0)) < 1e-9:
        return Decision("hold", "rule_flat", 1.0, "rule"), None

    ruled = _rule_profit_exit(snapshot)
    if ruled is not None:
        return ruled, None

    messages = _build_exit_messages(snapshot)
    conf_min = _confidence_min()
    try:
        resp = robust_chat_completion(
            messages=messages,
            timeout_ms=min(max(latency_budget_ms, 500), 4000),
            temperature=0.0,
            max_tokens=100,
            preferred_models=[primary_model_id()],
            use_cache=True,
        )
    except Exception:
        return Decision("hold", "nim_exit_error", 0.0, "rule"), None

    data = _extract_json(resp.content) or {}
    action = str(data.get("action") or "hold").strip().lower()
    if action not in ("hold", "flatten"):
        action = "hold"
    try:
        conf = float(data.get("confidence", 0.5))
    except Exception:
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    reason = str(data.get("reason") or "nim_exit").strip()[:200]
    if action == "flatten" and conf < conf_min:
        return Decision("hold", f"nim_low_confidence:{reason}", conf, "nim_low_confidence"), resp
    return Decision(action=action, reason=reason, confidence=conf, source="nim"), resp  # type: ignore[arg-type]
