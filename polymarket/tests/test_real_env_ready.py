"""Real-environment readiness gate tests."""

from __future__ import annotations

import os

from polymarket.research.local_lab.real_env_ready import check_code_safety, compose, run


def test_code_safety_passes_in_repo():
    sys = check_code_safety()
    assert sys["passed"] is True, sys
    assert sys["checks"]["execute_requires_confirm_env"]
    assert sys["checks"]["execute_restores_safe"]
    assert sys["checks"]["dna_aligned"]
    assert sys["checks"]["research_certified"]


def test_compose_system_ready_when_operator_blocked():
    system = {"passed": True}
    operator = {"operator_funded_region_ok": False, "can_execute_now": False}
    v = compose(system, operator)
    assert v["verdict"] == "REAL_ENV_SYSTEM_READY"
    assert v["system_ready"] is True
    assert v["go"] is False


def test_compose_go():
    system = {"passed": True}
    operator = {"operator_funded_region_ok": True, "can_execute_now": True}
    v = compose(system, operator)
    assert v["verdict"] == "REAL_ENV_GO"


def test_run_high_system_ready_exit_path():
    # Do not require operator GO in this cloud US egress
    rep = run(scale="high")
    assert rep["system_ready"] is True
    assert rep["verdict"] in (
        "REAL_ENV_SYSTEM_READY",
        "REAL_ENV_OPERATOR_READY",
        "REAL_ENV_GO",
    )
    assert "operator_checklist" in rep
    # Ensure we left SAFE
    assert os.getenv("POLY_LIVE_ARMED", "0") in ("0", "")
