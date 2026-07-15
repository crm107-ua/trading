#!/usr/bin/env python3
"""
Local connectivity + latency test for NVIDIA NIM (build.nvidia.com).

Requires:
  NVIDIA_API_KEY in environment (.env is fine; never commit).

Runs:
  - GET /models
  - POST /chat/completions (short JSON output)
Prints a small situation report (no PnL projections).
"""

from __future__ import annotations

import json
import time

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

from polymarket.src.ai.nvidia_client import (
    cache_models,
    pick_fast_models,
    robust_chat_completion,
)
from polymarket.src.ai.decision_engine import _extract_json


def main() -> None:
    t0 = time.perf_counter()
    cache = cache_models()
    mids = [m["id"] for m in cache.get("models") or [] if "id" in m]
    roster = pick_fast_models(mids)
    print(json.dumps({"models_total": len(mids), "fast_roster": roster[:6]}, indent=2))

    prompt = {
        "role": "user",
        "content": (
            "Return ONLY JSON: {\"ok\":true,\"note\":\"nim_smoke\"}."
        ),
    }
    resp = robust_chat_completion(messages=[prompt], preferred_models=roster, timeout_ms=3000, max_tokens=48)
    parsed = _extract_json(resp.content) or {}
    ok = parsed.get("ok") is True
    print(
        json.dumps(
            {
                "model": resp.model,
                "latency_ms": resp.latency_ms,
                "content": resp.content,
                "json_ok": ok,
                "parsed": parsed,
                "elapsed_ms_total": int((time.perf_counter() - t0) * 1000),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

