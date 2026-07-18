"""Invariants for the high-entry-bar grind selective / promoted champ DNA."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTIVE = ROOT / "config" / "maker_demo_grind_nim_selective.json"
BEST = ROOT / "config" / "maker_demo_grind_nim_best.json"

# Legacy DNA before selective promotion (for regression asserts).
LEGACY_MIN_EDGE = 0.026
LEGACY_MIN_Z = 0.85
LEGACY_MAX_ABS_EDGE = 0.09


def test_selective_and_best_share_promoted_entry_bar() -> None:
    sel = json.loads(SELECTIVE.read_text(encoding="utf-8"))
    best = json.loads(BEST.read_text(encoding="utf-8"))

    for cfg in (sel, best):
        assert cfg["preserve_selectivity"] is True
        assert cfg["cheap_side_only"] is True
        assert cfg["allow_rich_side_live"] is False
        assert cfg["max_entry_fills"] == 1
        assert float(cfg["min_edge"]) == 0.031
        assert float(cfg["min_z"]) == 1.0
        assert float(cfg["max_abs_edge"]) == 0.085
        assert float(cfg["min_quote_mid"]) == 0.28
        assert float(cfg["max_quote_mid"]) == 0.72
        assert float(cfg["soft_edge"]) >= float(cfg["min_edge"])
        assert float(cfg["hard_edge"]) >= float(cfg["soft_edge"])
        # Raised vs legacy
        assert float(cfg["min_edge"]) > LEGACY_MIN_EDGE
        assert float(cfg["min_z"]) > LEGACY_MIN_Z
        assert float(cfg["max_abs_edge"]) <= LEGACY_MAX_ABS_EDGE


def test_selective_floors_preserve_bar() -> None:
    from polymarket.web_lab.catalog import apply_live_clob_floors, load_scaled_config

    cfg, _meta = load_scaled_config("grind_nim_selective", 10.0)
    cfg = apply_live_clob_floors(cfg)
    assert float(cfg["min_edge"]) >= 0.031
    assert float(cfg["min_z"]) >= 1.0
    assert float(cfg["min_quote_mid"]) >= 0.28
    assert float(cfg["max_quote_mid"]) <= 0.72
