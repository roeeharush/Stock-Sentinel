"""Tests for stock_sentinel.scanner — Task 17.2."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_sentinel.models import ScannerCandidate
from stock_sentinel.scanner import (
    ScannerCooldownTracker,
    fetch_market_movers,
    filter_candidates,
    _fetch_screener_tickers,
    _fetch_ticker_info,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cand(ticker="NVDA", price=100.0, change_pct=5.0, volume=5_000_000,
          market_cap=50e9, reason="gainer"):
    return ScannerCandidate(
        ticker=ticker,
        price=price,
        change_pct=change_pct,
        volume=volume,
        market_cap=market_cap,
        reason=reason,
    )


# ── ScannerCooldownTracker ────────────────────────────────────────────────────

def test_cooldown_new_ticker_always_passes():
    tracker = ScannerCooldownTracker()
    assert tracker.should_scan("NVDA", 100.0, False) is True


def test_cooldown_within_window_no_exception():
    tracker = ScannerCooldownTracker()
    tracker.mark_alerted("NVDA", 100.0)
    # Just alerted — within 4-hour window, price unchanged, not 52w high
    assert tracker.should_scan("NVDA", 100.0, False) is False


def test_cooldown_within_window_52w_high_exception():
    tracker = ScannerCooldownTracker()
    tracker.mark_alerted("NVDA", 100.0)
    # 52-week high override
    assert tracker.should_scan("NVDA", 102.0, True) is True


def test_cooldown_within_window_price_move_exception():
    tracker = ScannerCooldownTracker()
    tracker.mark_alerted("NVDA", 100.0)
    # Price moved > 3% from last alert price
    assert tracker.should_scan("NVDA", 105.0, False) is True


def test_cooldown_after_window_passes():
    tracker = ScannerCooldownTracker()
    tracker.mark_alerted("AAPL", 200.0)
    # Manually expire the cooldown
    tracker._state["AAPL"]["alerted_at"] = datetime.now(timezone.utc) - timedelta(hours=5)
    assert tracker.should_scan("AAPL", 200.0, False) is True


def test_cooldown_mark_and_clear():
    tracker = ScannerCooldownTracker()
    tracker.mark_alerted("TSLA", 250.0)
    assert tracker.should_scan("TSLA", 250.0, False) is False
    tracker.clear("TSLA")
    assert tracker.should_scan("TSLA", 250.0, False) is True


def test_cooldown_price_move_below_threshold_stays_blocked():
    tracker = ScannerCooldownTracker()
    tracker.mark_alerted("AMZN", 100.0)
    # Only 1% move — below 3% threshold
    assert tracker.should_scan("AMZN", 101.0, False) is False


# ── filter_candidates ─────────────────────────────────────────────────────────

def test_filter_removes_low_market_cap():
    tracker = ScannerCooldownTracker()
    cands = [_cand("TINY", market_cap=500e6)]   # 500M < 2B
    result = filter_candidates(cands, tracker)
    assert result == []


def test_filter_removes_low_volume():
    tracker = ScannerCooldownTracker()
    cands = [_cand("THIN", volume=500_000)]      # 500K < 1M
    result = filter_candidates(cands, tracker)
    assert result == []


def test_filter_passes_qualifying_candidate():
    tracker = ScannerCooldownTracker()
    cands = [_cand("NVDA", market_cap=3e9, volume=2_000_000)]
    result = filter_candidates(cands, tracker)
    assert len(result) == 1
    assert result[0].ticker == "NVDA"


def test_filter_respects_cooldown():
    tracker = ScannerCooldownTracker()
    tracker.mark_alerted("AAPL", 150.0)
    cands = [_cand("AAPL", price=150.0, market_cap=3e9, volume=2_000_000)]
    result = filter_candidates(cands, tracker)
    assert result == []


def test_filter_multiple_mixed():
    tracker = ScannerCooldownTracker()
    cands = [
        _cand("GOOD", market_cap=5e9, volume=3_000_000),
        _cand("SMALL", market_cap=1e9, volume=3_000_000),   # fails market cap
        _cand("THIN", market_cap=5e9, volume=100_000),       # fails volume
    ]
    result = filter_candidates(cands, tracker)
    assert len(result) == 1
    assert result[0].ticker == "GOOD"


# ── _fetch_screener_tickers ────────────────────────────────────────────────────

def test_fetch_screener_tickers_returns_symbols():
    mock_result = {"quotes": [{"symbol": "NVDA"}, {"symbol": "AMZN"}]}
    with patch("stock_sentinel.scanner.yf.screen", return_value=mock_result):
        tickers = _fetch_screener_tickers("day_gainers", 10)
    assert tickers == ["NVDA", "AMZN"]


def test_fetch_screener_tickers_handles_api_failure():
    with patch("stock_sentinel.scanner.yf.screen", side_effect=Exception("rate limit")):
        tickers = _fetch_screener_tickers("day_gainers", 10)
    assert tickers == []


def test_fetch_screener_tickers_handles_empty_result():
    with patch("stock_sentinel.scanner.yf.screen", return_value={"quotes": []}):
        tickers = _fetch_screener_tickers("day_gainers", 10)
    assert tickers == []


# ── _fetch_ticker_info ────────────────────────────────────────────────────────

def test_fetch_ticker_info_returns_dict():
    mock_info = MagicMock()
    mock_info.last_price = 100.0
    mock_info.last_volume = 2_000_000
    mock_info.market_cap = 5e9
    mock_info.year_high = 120.0
    mock_info.previous_close = 95.0
    with patch("stock_sentinel.scanner.yf.Ticker") as MockTicker:
        MockTicker.return_value.fast_info = mock_info
        info = _fetch_ticker_info("NVDA")
    assert info is not None
    assert info["price"] == 100.0
    assert info["market_cap"] == 5e9
    assert info["volume"] == 2_000_000
    assert abs(info["change_pct"] - 5.26) < 0.1


def test_fetch_ticker_info_handles_error():
    with patch("stock_sentinel.scanner.yf.Ticker", side_effect=Exception("network")):
        info = _fetch_ticker_info("BROKEN")
    assert info is None


def test_fetch_ticker_info_52w_high_flag():
    mock_info = MagicMock()
    mock_info.last_price = 119.5    # within 1% of 52w high (120.0)
    mock_info.last_volume = 1_500_000
    mock_info.market_cap = 4e9
    mock_info.year_high = 120.0
    mock_info.previous_close = 115.0
    with patch("stock_sentinel.scanner.yf.Ticker") as MockTicker:
        MockTicker.return_value.fast_info = mock_info
        info = _fetch_ticker_info("AAPL")
    assert info["is_52w_high"] is True


# ── fetch_market_movers (integration stub) ────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_market_movers_returns_candidates():
    """fetch_market_movers returns ScannerCandidate list (all I/O mocked)."""
    screener_result = {"quotes": [{"symbol": "NVDA"}, {"symbol": "AMZN"}]}
    mock_info = MagicMock()
    mock_info.last_price = 200.0
    mock_info.last_volume = 5_000_000
    mock_info.market_cap = 100e9
    mock_info.year_high = 220.0
    mock_info.previous_close = 190.0

    with patch("stock_sentinel.scanner.yf.screen", return_value=screener_result), \
         patch("stock_sentinel.scanner.yf.Ticker") as MockTicker, \
         patch("stock_sentinel.scanner.asyncio.sleep", new_callable=AsyncMock):
        MockTicker.return_value.fast_info = mock_info
        candidates = await fetch_market_movers(top_n=5, jitter_min=0, jitter_max=0)

    assert len(candidates) >= 1
    assert all(isinstance(c, ScannerCandidate) for c in candidates)
    assert all(c.price > 0 for c in candidates)


@pytest.mark.asyncio
async def test_fetch_market_movers_deduplicates():
    """Same ticker appearing in multiple screeners is only included once."""
    screener_result = {"quotes": [{"symbol": "NVDA"}]}
    mock_info = MagicMock()
    mock_info.last_price = 100.0
    mock_info.last_volume = 2_000_000
    mock_info.market_cap = 50e9
    mock_info.year_high = 110.0
    mock_info.previous_close = 98.0

    with patch("stock_sentinel.scanner.yf.screen", return_value=screener_result), \
         patch("stock_sentinel.scanner.yf.Ticker") as MockTicker, \
         patch("stock_sentinel.scanner.asyncio.sleep", new_callable=AsyncMock):
        MockTicker.return_value.fast_info = mock_info
        candidates = await fetch_market_movers(top_n=10, jitter_min=0, jitter_max=0)

    tickers = [c.ticker for c in candidates]
    assert len(tickers) == len(set(tickers)), "Duplicate tickers found in results"
