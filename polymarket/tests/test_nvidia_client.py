from __future__ import annotations

from polymarket.src.ai.nvidia_client import pick_fast_models


def test_pick_fast_models_excludes_translate_and_vision():
    mids = [
        "nvidia/nemotron-mini-4b-instruct",
        "nvidia/riva-translate-4b-instruct-v1.1",
        "meta/llama-3.2-11b-vision-instruct",
        "nvidia/mistral-nemo-minitron-8b-8k-instruct",
    ]
    roster = pick_fast_models(mids)
    assert "nvidia/nemotron-mini-4b-instruct" in roster
    assert "nvidia/mistral-nemo-minitron-8b-8k-instruct" in roster
    assert "nvidia/riva-translate-4b-instruct-v1.1" not in roster
    assert "meta/llama-3.2-11b-vision-instruct" not in roster
    assert roster[0] == "nvidia/nemotron-mini-4b-instruct"
