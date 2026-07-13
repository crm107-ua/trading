"""Tests for CLOB book normalization."""

from polymarket.src.data.book_utils import best_bid_ask, top_levels, truncate_book


def test_best_bid_ask_unsorted_ws_order():
    bids = [{"price": "0.01", "size": "100"}, {"price": "0.10", "size": "50"}]
    asks = [{"price": "0.99", "size": "100"}, {"price": "0.90", "size": "50"}]
    bb, ba = best_bid_ask(bids, asks)
    assert bb == 0.10
    assert ba == 0.90


def test_truncate_near_touch():
    bids = [{"price": "0.01", "size": "1"}, {"price": "0.55", "size": "2"}]
    asks = [{"price": "0.99", "size": "1"}, {"price": "0.56", "size": "2"}]
    tb = truncate_book(bids, 1, side="bid")
    ta = truncate_book(asks, 1, side="ask")
    assert float(tb[0]["price"]) == 0.55
    assert float(ta[0]["price"]) == 0.56
