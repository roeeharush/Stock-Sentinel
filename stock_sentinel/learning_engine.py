"""Self-Learning Loop — weekly pattern recognition and dynamic filter generation.

Runs every Saturday post-market to analyse the past week's trades from the DB.

Detects four categories of toxic zones:
  1. RSI ceiling  — LONG signals above a threshold fail at high rates
  2. Ticker block — specific tickers consistently blow up
  3. Day block    — specific days of the week are structurally weak
  4. Hour block   — specific hours (ET) have poor follow-through

The resulting LearningReport is consumed by:
  - DynamicBlacklist (signal_filter.py) → auto-blocks next week's signals
  - build_learning_report_message (notifier.py) → sent to Telegram
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable

from stock_sentinel.models import LearningReport, PatternFinding

log = logging.getLogger(__name__)

# ── Detection thresholds ──────────────────────────────────────────────────────
_MIN_SAMPLES      = 2      # minimum trades in a bucket to flag a pattern
_MIN_FAILURE_RATE = 0.60   # 60%+ failure rate required to flag a pattern

_RSI_BUCKETS: list[tuple[float, float]] = [
    (75.0, 100.0),
    (70.0, 75.0),
    (65.0, 70.0),
]

_DAY_NAMES_HEB = {0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי", 4: "שישי", 5: "שבת", 6: "ראשון"}


# ── Trade classification helpers ──────────────────────────────────────────────

def _is_failed(trade: dict) -> bool:
    return trade.get("sl_hit") == 1 or trade.get("outcome") == "LOSS"


def _is_won(trade: dict) -> bool:
    return (
        trade.get("tp1_hit") == 1
        or trade.get("tp2_hit") == 1
        or trade.get("tp3_hit") == 1
        or trade.get("outcome") == "WIN"
    )


def _is_resolved(trade: dict) -> bool:
    return _is_failed(trade) or _is_won(trade)


def _parse_alerted_at(trade: dict) -> datetime:
    raw = trade.get("alerted_at", "")
    try:
        dt = datetime.fromisoformat(str(raw))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _to_et(dt: datetime) -> datetime:
    """Convert to US/Eastern (handles DST)."""
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        utc = dt.astimezone(timezone.utc)
        offset = timedelta(hours=-4 if 3 <= utc.month <= 11 else -5)
        return utc + offset


# ── Pattern detectors ─────────────────────────────────────────────────────────

def _detect_rsi_ceiling(
    long_trades: list[dict],
    patterns: list[PatternFinding],
) -> float | None:
    """Check if high RSI values correlate with LONG failures.

    Returns the tightest RSI ceiling detected, or None.
    """
    for low, high in _RSI_BUCKETS:
        bucket = [
            t for t in long_trades
            if t.get("rsi") is not None and low <= float(t["rsi"]) < high
        ]
        if len(bucket) < _MIN_SAMPLES:
            continue
        failed = sum(1 for t in bucket if _is_failed(t))
        rate   = failed / len(bucket)
        if rate >= _MIN_FAILURE_RATE:
            ceiling    = low
            action_heb = f"חסמתי עסקאות LONG עם RSI מעל {ceiling:.0f} לשבוע הבא"
            desc_heb   = f"RSI בין {low:.0f}–{high:.0f} בעסקאות LONG"
            patterns.append(PatternFinding(
                pattern_type="rsi_ceiling",
                description_heb=desc_heb,
                failure_rate=rate,
                sample_count=len(bucket),
                failed_count=failed,
                action_heb=action_heb,
                rsi_ceiling=ceiling,
            ))
            log.info("Pattern [rsi_ceiling=%.0f]: %d/%d failures (%.0f%%)", ceiling, failed, len(bucket), rate * 100)
            return ceiling  # return tightest ceiling found

    return None


def _detect_ticker_blocks(
    trades: list[dict],
    patterns: list[PatternFinding],
) -> list[str]:
    """Identify tickers with persistently high failure rates."""
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_ticker[t["ticker"]].append(t)

    blocked: list[str] = []
    for ticker, group in by_ticker.items():
        if len(group) < _MIN_SAMPLES:
            continue
        failed = sum(1 for t in group if _is_failed(t))
        rate   = failed / len(group)
        if rate >= _MIN_FAILURE_RATE:
            action_heb = f"חסמתי איתותים על {ticker} לשבוע הבא"
            desc_heb   = f"{ticker} — שיעור כישלון גבוה"
            patterns.append(PatternFinding(
                pattern_type="ticker_block",
                description_heb=desc_heb,
                failure_rate=rate,
                sample_count=len(group),
                failed_count=failed,
                action_heb=action_heb,
                blocked_ticker=ticker,
            ))
            log.info("Pattern [ticker=%s]: %d/%d failures (%.0f%%)", ticker, failed, len(group), rate * 100)
            blocked.append(ticker)

    return blocked


def _detect_day_blocks(
    trades: list[dict],
    patterns: list[PatternFinding],
) -> list[int]:
    """Identify weekdays (ET) with high failure rates. Returns weekday() ints."""
    by_day: dict[int, list[dict]] = defaultdict(list)
    for t in trades:
        et = _to_et(_parse_alerted_at(t))
        by_day[et.weekday()].append(t)

    blocked: list[int] = []
    for day_int, group in by_day.items():
        if len(group) < _MIN_SAMPLES:
            continue
        failed = sum(1 for t in group if _is_failed(t))
        rate   = failed / len(group)
        if rate >= _MIN_FAILURE_RATE:
            day_name   = _DAY_NAMES_HEB.get(day_int, str(day_int))
            action_heb = f"חסמתי איתותים בימי {day_name} לשבוע הבא"
            desc_heb   = f"יום {day_name} — שיעור כישלון גבוה"
            patterns.append(PatternFinding(
                pattern_type="day_block",
                description_heb=desc_heb,
                failure_rate=rate,
                sample_count=len(group),
                failed_count=failed,
                action_heb=action_heb,
                blocked_day=day_int,
            ))
            log.info("Pattern [day=%s]: %d/%d failures (%.0f%%)", day_name, failed, len(group), rate * 100)
            blocked.append(day_int)

    return blocked


def _detect_hour_blocks(
    trades: list[dict],
    patterns: list[PatternFinding],
) -> list[int]:
    """Identify ET hours with high failure rates."""
    by_hour: dict[int, list[dict]] = defaultdict(list)
    for t in trades:
        et = _to_et(_parse_alerted_at(t))
        by_hour[et.hour].append(t)

    blocked: list[int] = []
    for hour, group in by_hour.items():
        if len(group) < _MIN_SAMPLES:
            continue
        failed = sum(1 for t in group if _is_failed(t))
        rate   = failed / len(group)
        if rate >= _MIN_FAILURE_RATE:
            action_heb = f"חסמתי איתותים בשעה {hour:02d}:00–{hour+1:02d}:00 ET לשבוע הבא"
            desc_heb   = f"שעה {hour:02d}:00–{hour+1:02d}:00 ET — שיעור כישלון גבוה"
            patterns.append(PatternFinding(
                pattern_type="hour_block",
                description_heb=desc_heb,
                failure_rate=rate,
                sample_count=len(group),
                failed_count=failed,
                action_heb=action_heb,
                blocked_hour=hour,
            ))
            log.info("Pattern [hour=%02d ET]: %d/%d failures (%.0f%%)", hour, failed, len(group), rate * 100)
            blocked.append(hour)

    return blocked


# ── Projected win rate after blacklist ─────────────────────────────────────────

def _would_be_blocked(
    trade: dict,
    rsi_ceiling: float | None,
    blocked_tickers: list[str],
    blocked_days: list[int],
    blocked_hours: list[int],
) -> bool:
    """Return True if this trade would have been suppressed by the new blacklist."""
    if trade["ticker"] in blocked_tickers:
        return True
    et = _to_et(_parse_alerted_at(trade))
    if et.weekday() in blocked_days:
        return True
    if et.hour in blocked_hours:
        return True
    if (
        rsi_ceiling is not None
        and trade.get("direction") == "LONG"
        and trade.get("rsi") is not None
        and float(trade["rsi"]) > rsi_ceiling
    ):
        return True
    return False


# ── Main public API ───────────────────────────────────────────────────────────

def analyze_trades(
    trades: list[dict],
    week_start: datetime | None = None,
    week_end: datetime | None = None,
) -> LearningReport:
    """Analyse *trades* for failure patterns and return a LearningReport.

    *trades* should be the output of ``db.get_weekly_trades()``.
    *week_start* / *week_end* default to the past 7 days if not supplied.
    """
    now = datetime.now(timezone.utc)
    if week_end is None:
        week_end = now
    if week_start is None:
        week_start = now - timedelta(days=7)

    resolved   = [t for t in trades if _is_resolved(t)]
    unresolved = len(trades) - len(resolved)

    if not resolved:
        return LearningReport(
            analysis_date=now,
            week_start=week_start,
            week_end=week_end,
            total_trades=0,
            wins=0,
            losses=0,
            unresolved=unresolved,
            win_rate_before=0.0,
            win_rate_after=0.0,
            trades_filtered=0,
        )

    total  = len(resolved)
    losses = sum(1 for t in resolved if _is_failed(t))
    wins   = total - losses
    win_rate_before = wins / total

    patterns: list[PatternFinding] = []

    long_resolved = [t for t in resolved if t.get("direction") == "LONG"]
    rsi_ceiling   = _detect_rsi_ceiling(long_resolved, patterns)
    blocked_tickers = _detect_ticker_blocks(resolved, patterns)
    blocked_days    = _detect_day_blocks(resolved, patterns)
    blocked_hours   = _detect_hour_blocks(resolved, patterns)

    # Projected win rate after blacklist applied retrospectively
    surviving = [
        t for t in resolved
        if not _would_be_blocked(t, rsi_ceiling, blocked_tickers, blocked_days, blocked_hours)
    ]
    trades_filtered = total - len(surviving)
    if surviving:
        surviving_wins  = sum(1 for t in surviving if _is_won(t))
        win_rate_after  = surviving_wins / len(surviving)
    else:
        win_rate_after  = win_rate_before

    return LearningReport(
        analysis_date=now,
        week_start=week_start,
        week_end=week_end,
        total_trades=total,
        wins=wins,
        losses=losses,
        unresolved=unresolved,
        win_rate_before=win_rate_before,
        win_rate_after=win_rate_after,
        trades_filtered=trades_filtered,
        patterns=patterns,
        blocked_tickers=blocked_tickers,
        blocked_hours=blocked_hours,
        blocked_days=blocked_days,
        rsi_ceiling=rsi_ceiling,
    )


def run_weekly_learning(days: int = 7) -> LearningReport:
    """Synchronous entry point: fetches DB trades, analyses, returns LearningReport."""
    from stock_sentinel.db import get_weekly_trades
    trades = get_weekly_trades(days=days)
    now    = datetime.now(timezone.utc)
    return analyze_trades(
        trades,
        week_start=now - timedelta(days=days),
        week_end=now,
    )
