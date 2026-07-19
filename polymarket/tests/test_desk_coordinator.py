"""Tests anti-colisión desk_coordinator."""

from __future__ import annotations

from polymarket.research.local_lab.desk_coordinator import (
    effective_breadth,
    reset_coordinator,
    size_scale_for_cluster,
    try_claim,
)


def test_effective_breadth_less_than_n():
    assert effective_breadth(1, 0.85) == 1.0
    assert effective_breadth(4, 0.85) < 2.0


def test_size_scale_haircut():
    s = size_scale_for_cluster(4, 0.85)
    assert 0 < s < 1


def test_mutex_blocks_second_line(tmp_path, monkeypatch):
    path = tmp_path / "coord.json"
    monkeypatch.setenv("POLY_DESK_COORD_PATH", str(path))
    # re-import path binding — reset via API
    from polymarket.research.local_lab import desk_coordinator as dc

    monkeypatch.setattr(dc, "STATE_PATH", path)
    reset_coordinator()
    a = try_claim(line_id=1, market_id="M1", direction="up", mode="mutex_market")
    assert a.ok
    b = try_claim(line_id=2, market_id="M1", direction="up", mode="mutex_market")
    assert not b.ok
    assert b.reason == "mutex_held"
    c = try_claim(line_id=1, market_id="M1", direction="up", mode="mutex_market")
    assert c.ok


def test_ensemble_blocks_same_direction(tmp_path, monkeypatch):
    from polymarket.research.local_lab import desk_coordinator as dc

    path = tmp_path / "coord2.json"
    monkeypatch.setattr(dc, "STATE_PATH", path)
    reset_coordinator()
    a = try_claim(
        line_id=1, market_id="M2", direction="up", mode="ensemble_role", role="pulse"
    )
    assert a.ok
    b = try_claim(
        line_id=2, market_id="M2", direction="up", mode="ensemble_role", role="follow"
    )
    assert not b.ok
