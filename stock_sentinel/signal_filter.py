import logging
from datetime import datetime, timedelta, timezone
from stock_sentinel.models import TickerSnapshot
from stock_sentinel import config
from stock_sentinel.config import (
    SENTIMENT_MIN_TWEETS, SENTIMENT_MIN_HEADLINES,
    SENTIMENT_MIN_RSS_HEADLINES, COOLDOWN_MINUTES,
    WEIGHT_RSS, WEIGHT_NEWS, WEIGHT_TWITTER,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Blacklist (populated by Learning Engine every Saturday)
# ─────────────────────────────────────────────────────────────────────────────

def _to_et(dt: datetime) -> datetime:
    """Convert a UTC datetime to US/Eastern (handles DST)."""
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        from datetime import timedelta as _td
        utc = dt.astimezone(timezone.utc)
        # EDT = UTC-4 (Mar–Nov), EST = UTC-5 (Nov–Mar) — approximate
        offset = _td(hours=-4 if 3 <= utc.month <= 11 else -5)
        return utc + offset


class DynamicBlacklist:
    """Runtime blacklist updated weekly by the Self-Learning Engine.

    Holds 'toxic zones' identified from historical failures.  Each rule
    expires after 7 days; once expired, ``is_active()`` returns False and
    ``should_alert`` skips the check entirely.
    """

    def __init__(self) -> None:
        self.blocked_tickers: set[str] = set()
        self.blocked_hours:   set[int] = set()   # ET hours (0-23)
        self.blocked_days:    set[int] = set()   # weekday() 0=Mon … 6=Sun
        self.rsi_ceiling:     float | None = None
        self.expires_at:      datetime | None = None

    # ── Public interface ──────────────────────────────────────────────────────

    def is_active(self) -> bool:
        """True when the blacklist has been populated and has not expired."""
        return (
            self.expires_at is not None
            and datetime.now(timezone.utc) < self.expires_at
        )

    def has_rules(self) -> bool:
        """True when at least one blocking rule is set."""
        return bool(
            self.blocked_tickers
            or self.blocked_hours
            or self.blocked_days
            or self.rsi_ceiling is not None
        )

    def apply_report(self, report) -> None:  # report: LearningReport (avoid circular)
        """Load rules from a LearningReport and set expiry to 7 days from now."""
        self.blocked_tickers = set(report.blocked_tickers)
        self.blocked_hours   = set(report.blocked_hours)
        self.blocked_days    = set(report.blocked_days)
        self.rsi_ceiling     = report.rsi_ceiling
        self.expires_at      = datetime.now(timezone.utc) + timedelta(days=7)
        log.info(
            "DynamicBlacklist updated — tickers=%s  hours=%s  days=%s  rsi_ceil=%s  expires=%s",
            self.blocked_tickers, self.blocked_hours, self.blocked_days,
            self.rsi_ceiling,
            self.expires_at.strftime("%Y-%m-%d %H:%M UTC"),
        )

    def clear(self) -> None:
        """Remove all rules (used in tests / manual override)."""
        self.blocked_tickers = set()
        self.blocked_hours   = set()
        self.blocked_days    = set()
        self.rsi_ceiling     = None
        self.expires_at      = None

    def is_blocked(
        self,
        ticker: str,
        direction: str,
        rsi: float,
        signal_time: datetime,
    ) -> tuple[bool, str]:
        """Return (True, reason_heb) if the signal falls in a toxic zone.

        Returns (False, "") when not blocked.
        """
        if not self.is_active():
            return False, ""

        if ticker in self.blocked_tickers:
            return True, f"טיקר {ticker} חסום — אזור רעיל שזוהה בניתוח שבועי"

        et = _to_et(signal_time)

        if et.weekday() in self.blocked_days:
            _day_heb = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
            day_name = _day_heb[et.weekday()]
            return True, f"יום {day_name} חסום — אזור רעיל שזוהה בניתוח שבועי"

        if et.hour in self.blocked_hours:
            return True, f"שעה {et.hour:02d}:00 ET חסומה — אזור רעיל שזוהה בניתוח שבועי"

        if direction == "LONG" and self.rsi_ceiling is not None and rsi > self.rsi_ceiling:
            return True, (
                f"RSI {rsi:.1f} מעל תקרת {self.rsi_ceiling:.0f} — "
                "אזור רעיל שזוהה בניתוח שבועי"
            )

        return False, ""


def _twitter_ok(snapshot: TickerSnapshot) -> bool:
    s = snapshot.sentiment
    return s is not None and not s.failed and s.tweet_count >= SENTIMENT_MIN_TWEETS


def _news_ok(snapshot: TickerSnapshot) -> bool:
    n = snapshot.news_sentiment
    return n is not None and not n.failed and n.headline_count >= SENTIMENT_MIN_HEADLINES


def _rss_ok(snapshot: TickerSnapshot) -> bool:
    r = snapshot.rss_sentiment
    return r is not None and not r.failed and r.headline_count >= SENTIMENT_MIN_RSS_HEADLINES


def combined_sentiment_score(snapshot: TickerSnapshot) -> float:
    """Return 40/40/20 (RSS/news/twitter) weighted score with graceful degradation.

    Degradation: weights of unavailable sources are redistributed proportionally
    among available sources.
    """
    t_ok = _twitter_ok(snapshot)
    n_ok = _news_ok(snapshot)
    r_ok = _rss_ok(snapshot)

    if not t_ok and not n_ok and not r_ok:
        return 0.0

    # Build weighted sum from available sources
    weights = {}
    if r_ok:
        weights["rss"] = (WEIGHT_RSS, snapshot.rss_sentiment.score)
    if n_ok:
        weights["news"] = (WEIGHT_NEWS, snapshot.news_sentiment.score)
    if t_ok:
        weights["twitter"] = (WEIGHT_TWITTER, snapshot.sentiment.score)

    total_weight = sum(w for w, _ in weights.values())
    return sum((w / total_weight) * s for w, s in weights.values())


def should_alert(
    snapshot: TickerSnapshot,
    blacklist: DynamicBlacklist | None = None,
) -> bool:
    t = snapshot.technical
    if t is None or t.direction == "NEUTRAL":
        return False

    if t.technical_score < config.TECHNICAL_SCORE_MIN:
        return False

    if not _twitter_ok(snapshot) and not _news_ok(snapshot) and not _rss_ok(snapshot):
        return False

    score = combined_sentiment_score(snapshot)
    if t.direction == "LONG" and score < config.TRADE_SENTIMENT_THRESHOLD:
        return False
    if t.direction == "SHORT" and score > -config.TRADE_SENTIMENT_THRESHOLD:
        return False

    if snapshot.last_alert_at is not None:
        if datetime.now(timezone.utc) - snapshot.last_alert_at < timedelta(minutes=COOLDOWN_MINUTES):
            return False

    # Dynamic blacklist gate (populated by Self-Learning Engine)
    if blacklist is not None and blacklist.is_active():
        blocked, reason = blacklist.is_blocked(
            ticker=snapshot.ticker,
            direction=t.direction,
            rsi=t.rsi,
            signal_time=datetime.now(timezone.utc),
        )
        if blocked:
            log.info("Signal blocked for %s: %s", snapshot.ticker, reason)
            return False

    return True


def update_cooldown(snapshot: TickerSnapshot) -> TickerSnapshot:
    snapshot.last_alert_at = datetime.now(timezone.utc)
    return snapshot
