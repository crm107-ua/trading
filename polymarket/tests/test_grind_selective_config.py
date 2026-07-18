"""Invariants for the high-entry-bar grind selective config."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTIVE = ROOT / "config" / "maker_demo_grind_nim_selective.json"
BASE = ROOT / "config" / "maker_demo_grind_nim_best.json"


def test_selective_raises_entry_bar_vs_base() -> None:
    sel = json.loads(SELECTIVE.read_text(encoding="utf-8"))
    base = json.loads(BASE.read_text(encoding="utf-8"))

    assert sel["preserve_selectivity"] is True
    assert sel["cheap_side_only"] is True
    assert sel["allow_rich_side_live"] is False
    assert sel["max_entry_fills"] == 1

    assert float(sel["min_edge"]) > float(base["min_edge"])
    assert float(sel["min_z"]) > float(base["min_z"])
    assert float(sel["max_abs_edge"]) <= float(base["max_abs_edge"])
    # v2: keep base mid band (narrow mid starved into bad regimes in v1)
    assert float(sel["min_quote_mid"]) == float(base["min_quote_mid"])
    assert float(sel["max_quote_mid"]) == float(base["max_quote_mid"])

    # Hierarchy: soft >= min, hard >= soft
    assert float(sel["soft_edge"]) >= float(sel["min_edge"])
    assert float(sel["hard_edge"]) >= float(sel["soft_edge"])


def test_selective_floors_preserve_bar() -> None:
    from polymarket.web_lab.catalog import apply_live_clob_floors, load_scaled_config

    cfg, _meta = load_scaled_config("grind_nim_selective", 10.0)
    cfg = apply_live_clob_floors(cfg)
    assert float(cfg["min_edge"]) >= 0.031
    assert float(cfg["min_z"]) >= 1.0
    assert float(cfg["min_quote_mid"]) >= 0.28
    assert float(cfg["max_quote_mid"]) <= 0.72
