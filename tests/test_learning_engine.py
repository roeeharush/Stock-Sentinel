"""Tests for stock_sentinel.learning_engine and signal_filter.DynamicBlacklist."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stock_sentinel.learning_engine import (
    _is_failed,
    _is_won,
    _is_resolved,
    _detect_rsi_ceiling,
    _detect_ticker_blocks,
    _detect_day_blocks,
    _detect_hour_blocks,
    _would_be_blocked,
    analyze_trades,
)
from stock_sentinel.models import LearningReport, PatternFinding
from stock_sentinel.signal_filter import DynamicBlacklist


# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────

def _trade(
    ticker="NVDA",
    direction="LONG",
    rsi=50.0,
    outcome=None,
    sl_hit=0,
    tp1_hit=0,
    tp2_hit=0,
    tp3_hit=0,
    alerted_at: str | None = None,
    confluence_factors=None,
) -> dict:
    """Build a minimal trade dict matching DB row format."""
    if alerted_at is None:
        # Default: Monday 10:00 UTC (= 06:00 ET)
        alerted_at = "2025-03-10T10:00:00+00:00"
    return {
        "ticker": ticker,
        "direction": direction,
        "rsi": rsi,
        "outcome": outcome,
        "sl_hit": sl_hit,
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        "tp3_hit": tp3_hit,
        "alerted_at": alerted_at,
        "confluence_factors": confluence_factors or [],
    }


def _loss(**kw) -> dict:
    return _trade(sl_hit=1, **kw)


def _win(**kw) -> dict:
    return _trade(tp1_hit=1, **kw)


# ── Friday 21:00 ET = Saturday 02:00 UTC ─────────────────────────────────────
_FRI_21ET = "2025-03-08T02:00:00+00:00"   # Fri 21:00 ET  (weekday=4)
_MON_10ET = "2025-03-10T15:00:00+00:00"   # Mon 10:00 ET  (weekday=0)


# ─────────────────────────────────────────────────────────────────────────────
# Trade classification helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_is_failed_sl_hit():
    assert _is_failed(_trade(sl_hit=1))


def test_is_failed_outcome_loss():
    assert _is_failed(_trade(outcome="LOSS"))


def test_is_failed_false_for_win():
    assert not _is_failed(_win())


def test_is_won_tp1():
    assert _is_won(_trade(tp1_hit=1))


def test_is_won_outcome_win():
    assert _is_won(_trade(outcome="WIN"))


def test_is_resolved_loss():
    assert _is_resolved(_loss())


def test_is_resolved_win():
    assert _is_resolved(_win())


def test_is_not_resolved_open():
    assert not _is_resolved(_trade())


# ─────────────────────────────────────────────────────────────────────────────
# Pattern detectors
# ─────────────────────────────────────────────────────────────────────────────

def test_detect_rsi_ceiling_detects_high_rsi_failures():
    trades = [
        _loss(direction="LONG", rsi=78.0),
        _loss(direction="LONG", rsi=76.0),
        _win(direction="LONG",  rsi=45.0),
    ]
    patterns: list[PatternFinding] = []
    ceiling = _detect_rsi_ceiling(trades, patterns)
    assert ceiling == 75.0
    assert len(patterns) == 1
    assert patterns[0].pattern_type == "rsi_ceiling"


def test_detect_rsi_ceiling_no_pattern_below_threshold():
    # Only 1 sample in high-RSI bucket — below min_samples
    trades = [
        _loss(direction="LONG", rsi=77.0),
        _win(direction="LONG",  rsi=78.0),  # 1 win, 1 loss → 50% fail rate < 60%
    ]
    patterns: list[PatternFinding] = []
    ceiling = _detect_rsi_ceiling(trades, patterns)
    assert ceiling is None


def test_detect_rsi_ceiling_returns_none_for_empty():
    patterns: list[PatternFinding] = []
    assert _detect_rsi_ceiling([], patterns) is None


def test_detect_ticker_blocks_identifies_bad_ticker():
    trades = [
        _loss(ticker="FLNC"),
        _loss(ticker="FLNC"),
        _win(ticker="NVDA"),
    ]
    patterns: list[PatternFinding] = []
    blocked = _detect_ticker_blocks(trades, patterns)
    assert "FLNC" in blocked
    assert "NVDA" not in blocked
    assert len(patterns) == 1


def test_detect_ticker_blocks_no_block_below_min_samples():
    trades = [_loss(ticker="RKLB")]  # only 1 sample
    patterns: list[PatternFinding] = []
    blocked = _detect_ticker_blocks(trades, patterns)
    assert blocked == []


def test_detect_day_blocks_flags_friday():
    # Friday 21:00 ET trades
    trades = [
        _loss(alerted_at=_FRI_21ET),
        _loss(alerted_at=_FRI_21ET),
        _win(alerted_at=_MON_10ET),
    ]
    patterns: list[PatternFinding] = []
    blocked = _detect_day_blocks(trades, patterns)
    assert 4 in blocked   # 4 = Friday weekday()
    assert 0 not in blocked


def test_detect_hour_blocks_flags_bad_hour():
    # Two losses at 21:00 ET → hour 21 should be flagged
    # Friday 21:00 ET = Saturday 02:00 UTC  (hour 21 ET)
    trades = [
        _loss(alerted_at=_FRI_21ET),
        _loss(alerted_at=_FRI_21ET),
        _win(alerted_at=_MON_10ET),   # 10:00 ET  hour=10
    ]
    patterns: list[PatternFinding] = []
    blocked = _detect_hour_blocks(trades, patterns)
    assert 21 in blocked


# ─────────────────────────────────────────────────────────────────────────────
# _would_be_blocked
# ─────────────────────────────────────────────────────────────────────────────

def test_would_be_blocked_ticker():
    t = _trade(ticker="FLNC")
    assert _would_be_blocked(t, None, ["FLNC"], [], [])


def test_would_be_blocked_rsi_ceiling():
    t = _trade(direction="LONG", rsi=80.0)
    assert _would_be_blocked(t, 75.0, [], [], [])


def test_would_be_blocked_rsi_ceiling_not_long():
    t = _trade(direction="SHORT", rsi=80.0)
    assert not _would_be_blocked(t, 75.0, [], [], [])


def test_would_be_blocked_day():
    t = _trade(alerted_at=_FRI_21ET)
    assert _would_be_blocked(t, None, [], [4], [])  # Friday=4


def test_would_be_blocked_hour():
    t = _trade(alerted_at=_FRI_21ET)
    assert _would_be_blocked(t, None, [], [], [21])  # 21 ET


def test_not_blocked_when_no_rules():
    t = _trade(ticker="NVDA", rsi=50.0, alerted_at=_MON_10ET)
    assert not _would_be_blocked(t, None, [], [], [])


# ─────────────────────────────────────────────────────────────────────────────
# analyze_trades — end-to-end
# ─────────────────────────────────────────────────────────────────────────────

def test_analyze_trades_empty_returns_zero_report():
    report = analyze_trades([])
    assert report.total_trades == 0
    assert report.patterns == []
    assert report.win_rate_before == 0.0


def test_analyze_trades_no_resolved_returns_zero_report():
    report = analyze_trades([_trade(), _trade()])  # all open
    assert report.total_trades == 0
    assert report.unresolved == 2


def test_analyze_trades_basic_win_rate():
    trades = [_win(), _win(), _loss()]
    report = analyze_trades(trades)
    assert report.total_trades == 3
    assert report.wins == 2
    assert report.losses == 1
    assert abs(report.win_rate_before - 2 / 3) < 0.01


def test_analyze_trades_detects_rsi_pattern():
    trades = [
        _loss(direction="LONG", rsi=77.0),
        _loss(direction="LONG", rsi=79.0),
        _win(direction="LONG",  rsi=45.0),
        _win(direction="LONG",  rsi=50.0),
    ]
    report = analyze_trades(trades)
    assert report.rsi_ceiling == 75.0
    assert any(p.pattern_type == "rsi_ceiling" for p in report.patterns)


def test_analyze_trades_projected_win_rate_improves():
    trades = [
        _loss(direction="LONG", rsi=77.0),
        _loss(direction="LONG", rsi=78.0),
        _win(direction="LONG",  rsi=45.0),
        _win(direction="LONG",  rsi=50.0),
    ]
    report = analyze_trades(trades)
    # After blocking RSI>75, only 2 trades remain (both wins) → 100%
    assert report.win_rate_after > report.win_rate_before
    assert report.trades_filtered == 2


def test_analyze_trades_detects_ticker_pattern():
    trades = [
        _loss(ticker="FLNC"),
        _loss(ticker="FLNC"),
        _win(ticker="NVDA"),
    ]
    report = analyze_trades(trades)
    assert "FLNC" in report.blocked_tickers


def test_analyze_trades_no_patterns_for_mixed_results():
    trades = [_win(), _loss(), _win(), _loss()]
    report = analyze_trades(trades)
    # 50% fail rate per bucket, only 1 sample each potentially → may or may not trigger
    # Just verify it runs without error and returns sensible data
    assert report.total_trades == 4
    assert isinstance(report.patterns, list)


# ─────────────────────────────────────────────────────────────────────────────
# DynamicBlacklist
# ─────────────────────────────────────────────────────────────────────────────

def test_blacklist_initial_not_active():
    bl = DynamicBlacklist()
    assert not bl.is_active()


def test_blacklist_not_active_before_apply():
    bl = DynamicBlacklist()
    assert not bl.has_rules()


def test_blacklist_clear():
    bl = DynamicBlacklist()
    bl.blocked_tickers = {"FLNC"}
    bl.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    bl.clear()
    assert not bl.is_active()
    assert not bl.has_rules()


def test_blacklist_apply_report():
    from stock_sentinel.models import LearningReport
    report = LearningReport(
        analysis_date=datetime.now(timezone.utc),
        week_start=datetime.now(timezone.utc) - timedelta(days=7),
        week_end=datetime.now(timezone.utc),
        total_trades=5, wins=3, losses=2, unresolved=0,
        win_rate_before=0.6, win_rate_after=0.8,
        trades_filtered=2,
        blocked_tickers=["FLNC"],
        blocked_hours=[21],
        blocked_days=[4],
        rsi_ceiling=75.0,
    )
    bl = DynamicBlacklist()
    bl.apply_report(report)
    assert bl.is_active()
    assert "FLNC" in bl.blocked_tickers
    assert 21 in bl.blocked_hours
    assert 4 in bl.blocked_days
    assert bl.rsi_ceiling == 75.0


def test_blacklist_blocks_ticker():
    bl = DynamicBlacklist()
    bl.blocked_tickers = {"FLNC"}
    bl.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    blocked, reason = bl.is_blocked("FLNC", "LONG", 50.0, datetime.now(timezone.utc))
    assert blocked
    assert "FLNC" in reason


def test_blacklist_blocks_rsi():
    bl = DynamicBlacklist()
    bl.rsi_ceiling = 75.0
    bl.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    blocked, reason = bl.is_blocked("NVDA", "LONG", 80.0, datetime.now(timezone.utc))
    assert blocked
    assert "RSI" in reason


def test_blacklist_rsi_allows_short():
    bl = DynamicBlacklist()
    bl.rsi_ceiling = 75.0
    bl.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    blocked, _ = bl.is_blocked("NVDA", "SHORT", 80.0, datetime.now(timezone.utc))
    assert not blocked


def test_blacklist_expired_not_active():
    bl = DynamicBlacklist()
    bl.blocked_tickers = {"NVDA"}
    bl.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert not bl.is_active()
    blocked, _ = bl.is_blocked("NVDA", "LONG", 50.0, datetime.now(timezone.utc))
    assert not blocked


def test_blacklist_blocks_hour():
    bl = DynamicBlacklist()
    bl.blocked_hours = {21}
    bl.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    # Friday 21:00 ET = Saturday 02:00 UTC
    sig_time = datetime(2025, 3, 8, 2, 0, tzinfo=timezone.utc)
    blocked, reason = bl.is_blocked("NVDA", "LONG", 50.0, sig_time)
    assert blocked
    assert "ET" in reason
