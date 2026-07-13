from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from polymarket.src.ai.nvidia_client import NimResponse, robust_chat_completion


ActionType = Literal["quote", "cancel_replace", "hold"]


@dataclass(frozen=True)
class Decision:
    action: ActionType
    reason: str
    confidence: float


def _extract_json(text: str) -> dict[str, Any] | None:
    """
    Extract first JSON object from text (robust to pre/postamble).
    """
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def decide_quote_action(
    *,
    snapshot: dict[str, Any],
    latency_budget_ms: int = 750,
    preferred_models: list[str] | None = None,
) -> tuple[Decision, NimResponse | None]:
    """
    Ask NVIDIA NIM for a structured decision about whether to quote now,
    cancel/replace, or hold. Does NOT change pricing parameters — only the action.
    """
    prompt = {
        "role": "user",
        "content": (
            "You are a risk-averse trading assistant for a retail Polymarket maker bot.\n"
            "Return ONLY a JSON object with keys:\n"
            '  action: one of ["quote","cancel_replace","hold"]\n'
            "  confidence: float 0..1\n"
            "  reason: short string\n"
            "\n"
            "Rules:\n"
            "- Prefer HOLD if unsure.\n"
            "- If feed is stale or book missing, choose HOLD.\n"
            "- If market spread is wide and fair is stable, choose QUOTE.\n"
            "- If spot moved a lot since last quote, choose CANCEL_REPLACE.\n"
            "\n"
            f"Snapshot:\n{json.dumps(snapshot, ensure_ascii=False)}"
        ),
    }
    try:
        resp = robust_chat_completion(
            messages=[prompt],
            timeout_ms=min(max(latency_budget_ms, 250), 1200),
            temperature=0.0,
            max_tokens=128,
            preferred_models=preferred_models,
        )
    except Exception:
        # Fallback deterministic: hold
        return Decision(action="hold", reason="nim_error_or_timeout", confidence=0.0), None

    data = _extract_json(resp.content) or {}
    action = data.get("action")
    if action not in ("quote", "cancel_replace", "hold"):
        return Decision(action="hold", reason="nim_bad_format", confidence=0.0), resp
    try:
        conf = float(data.get("confidence", 0.5))
    except Exception:
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    reason = str(data.get("reason") or "nim_decision").strip()[:200]
    return Decision(action=action, reason=reason, confidence=conf), resp

