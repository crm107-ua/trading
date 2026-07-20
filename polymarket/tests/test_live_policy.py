"""Tests política SAFE / checklist / kill lines."""

from __future__ import annotations

import json
from pathlib import Path

from polymarket.src.execution import live_policy as pol


def test_validate_real_blocked_without_checklist(tmp_path, monkeypatch):
    path = tmp_path / "live_checklist.json"
    path.write_text(json.dumps({"ok": False, "dry_sessions_clean": 0}), encoding="utf-8")
    monkeypatch.setenv("POLY_LIVE_CHECKLIST_PATH", str(path))
    monkeypatch.delenv("POLY_LIVE_BYPASS_CHECKLIST", raising=False)
    ok, msg = pol.validate_real_start(1.2, 6.0)
    assert ok is False
    assert "Checklist" in msg or "checklist" in msg.lower() or "dry" in msg.lower()


def test_validate_real_blocked_low_balance(tmp_path, monkeypatch):
    path = tmp_path / "live_checklist.json"
    path.write_text(
        json.dumps({"ok": True, "dry_sessions_clean": 10, "required": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("POLY_LIVE_CHECKLIST_PATH", str(path))
    monkeypatch.delenv("POLY_LIVE_BYPASS_CHECKLIST", raising=False)
    ok, msg = pol.validate_real_start(1.2, 0.83)
    assert ok is False
    assert "5" in msg or "Saldo" in msg


def test_validate_real_ok_with_checklist_and_balance(tmp_path, monkeypatch):
    path = tmp_path / "live_checklist.json"
    path.write_text(
        json.dumps({"ok": True, "dry_sessions_clean": 10, "required": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("POLY_LIVE_CHECKLIST_PATH", str(path))
    monkeypatch.delenv("POLY_LIVE_BYPASS_CHECKLIST", raising=False)
    # reset day pnl
    monkeypatch.setattr(pol, "DAY_PNL_PATH", tmp_path / "day.json")
    monkeypatch.setattr(
        pol,
        "check_geoblock",
        lambda **_: pol.GeoBlockStatus(blocked=False, ip="1.1.1.1", country="IE"),
    )
    ok, msg = pol.validate_real_start(1.2, 6.0)
    assert ok is True, msg


def test_capital_cap_fase_d(tmp_path, monkeypatch):
    path = tmp_path / "live_checklist.json"
    path.write_text(
        json.dumps({"ok": True, "dry_sessions_clean": 12, "required": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("POLY_LIVE_CHECKLIST_PATH", str(path))
    monkeypatch.setattr(pol, "DAY_PNL_PATH", tmp_path / "day.json")
    monkeypatch.setattr(
        pol,
        "check_geoblock",
        lambda **_: pol.GeoBlockStatus(blocked=False, ip="1.1.1.1", country="IE"),
    )
    ok, msg = pol.validate_real_start(3.0, 10.0)
    assert ok is True, msg
    ok2, msg2 = pol.validate_real_start(6.0, 10.0)
    assert ok2 is False
    assert "5.0" in msg2


def test_kill_line_reason():
    assert pol.kill_line_reason("DUST_STUCK inv=1") == "dust_stuck"
    assert pol.kill_line_reason("FLATTEN_WRONG_TOKEN bal=0") == "wrong_token"
    assert pol.kill_line_reason("KILL_SESSION net=-0.5") == "kill_session"
    assert pol.kill_line_reason("GEOBLOCK_KILL region") == "geoblock"
    assert pol.kill_line_reason("Trading restricted in your region") == "geoblock"
    assert pol.kill_line_reason("paper wait_edge") is None


def test_validate_real_blocked_by_geoblock(tmp_path, monkeypatch):
    path = tmp_path / "live_checklist.json"
    path.write_text(
        json.dumps({"ok": True, "dry_sessions_clean": 10, "required": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("POLY_LIVE_CHECKLIST_PATH", str(path))
    monkeypatch.delenv("POLY_LIVE_BYPASS_CHECKLIST", raising=False)
    monkeypatch.delenv("POLY_LIVE_SKIP_GEOBLOCK", raising=False)
    monkeypatch.setattr(pol, "DAY_PNL_PATH", tmp_path / "day.json")
    monkeypatch.setattr(
        pol,
        "check_geoblock",
        lambda **_: pol.GeoBlockStatus(
            blocked=True, ip="1.2.3.4", country="US", region="OH"
        ),
    )
    ok, msg = pol.validate_real_start(2.5, 10.0)
    assert ok is False
    assert "GEOBLOCK" in msg


def test_validate_real_ok_when_geoblock_clear(tmp_path, monkeypatch):
    path = tmp_path / "live_checklist.json"
    path.write_text(
        json.dumps({"ok": True, "dry_sessions_clean": 10, "required": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("POLY_LIVE_CHECKLIST_PATH", str(path))
    monkeypatch.setattr(pol, "DAY_PNL_PATH", tmp_path / "day.json")
    monkeypatch.setattr(
        pol,
        "check_geoblock",
        lambda **_: pol.GeoBlockStatus(blocked=False, ip="9.9.9.9", country="IE"),
    )
    ok, msg = pol.validate_real_start(2.5, 10.0)
    assert ok is True, msg


def test_save_checklist_marks_ok(tmp_path, monkeypatch):
    path = tmp_path / "c.json"
    monkeypatch.setenv("POLY_LIVE_CHECKLIST_PATH", str(path))
    pol.save_checklist({"dry_sessions_clean": 10, "ok": False})
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["ok"] is True
