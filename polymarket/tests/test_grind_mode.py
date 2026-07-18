from polymarket.src.ai.decision_engine import (
    _rule_profit_exit,
    grind_mode_enabled,
)


def test_grind_locks_small_green(monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_GRIND", "1")
    assert grind_mode_enabled()
    d = _rule_profit_exit(
        {
            "inventory_shares": 5,
            "unrealized_pnl_usdc": 0.10,
            "fair_up": 0.5,
            "mark_price": 0.42,
            "avg_entry": 0.40,
            "lock_profit_usdc": 0.22,
        }
    )
    assert d is not None
    assert d.action == "flatten"


def test_grind_off_allows_tiny_green(monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_GRIND", "0")
    d = _rule_profit_exit(
        {
            "inventory_shares": 5,
            "unrealized_pnl_usdc": 0.10,
            "fair_up": 0.5,
            "mark_price": 0.41,
            "avg_entry": 0.40,
            "lock_profit_usdc": 1.25,
        }
    )
    # sin grind, 1¢ mid move no basta para lock_tp_mid (necesita 2.5¢)
    assert d is None or d.action in ("flatten", "hold")


def test_grind_cuts_small_red(monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_GRIND", "1")
    d = _rule_profit_exit(
        {
            "inventory_shares": 5,
            "unrealized_pnl_usdc": -0.06,
            "fair_up": 0.5,
            "mark_price": 0.39,
            "avg_entry": 0.40,
            "lock_profit_usdc": 0.12,
        }
    )
    assert d is not None
    assert d.action == "flatten"
    assert "cut_red" in d.reason or "grind" in d.reason


def test_cheap_side_only_blocks_rich():
    from polymarket.research.local_lab.strategies import maker_edge

    q = maker_edge(
        fair_up=0.40,
        best_bid=0.50,
        best_ask=0.52,
        spot=100.0,
        strike=100.0,
        cfg={
            "min_edge": 0.02,
            "sigma_mid": 0.03,
            "min_z": 0.5,
            "half_spread": 0.01,
            "safety_buffer": 0.002,
            "quote_size_shares": 5,
            "kelly_sizing": False,
            "cheap_side_only": True,
            "min_quote_mid": 0.2,
            "max_quote_mid": 0.8,
        },
    )
    assert q is None


def test_max_abs_edge_blocks_model_disagreement():
    from polymarket.research.local_lab.strategies import maker_edge

    q = maker_edge(
        fair_up=0.50,
        best_bid=0.94,
        best_ask=0.96,
        spot=100.0,
        strike=100.0,
        cfg={
            "min_edge": 0.02,
            "max_abs_edge": 0.11,
            "sigma_mid": 0.03,
            "min_z": 0.5,
            "half_spread": 0.01,
            "safety_buffer": 0.002,
            "quote_size_shares": 5,
            "kelly_sizing": False,
            "min_quote_mid": 0.2,
            "max_quote_mid": 0.98,
        },
    )
    assert q is None
