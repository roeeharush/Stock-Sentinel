from datetime import datetime, timedelta, timezone
from stock_sentinel.models import TickerSnapshot
from stock_sentinel.config import (
    SENTIMENT_MIN_TWEETS, SENTIMENT_MIN_HEADLINES,
    SENTIMENT_MIN_RSS_HEADLINES, COOLDOWN_MINUTES,
)


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
        weights["rss"] = (0.40, snapshot.rss_sentiment.score)
    if n_ok:
        weights["news"] = (0.40, snapshot.news_sentiment.score)
    if t_ok:
        weights["twitter"] = (0.20, snapshot.sentiment.score)

    total_weight = sum(w for w, _ in weights.values())
    return sum((w / total_weight) * s for w, s in weights.values())


def should_alert(snapshot: TickerSnapshot) -> bool:
    t = snapshot.technical
    if t is None or t.direction == "NEUTRAL":
        return False

    if not _twitter_ok(snapshot) and not _news_ok(snapshot) and not _rss_ok(snapshot):
        return False

    score = combined_sentiment_score(snapshot)
    if t.direction == "LONG" and score <= 0:
        return False
    if t.direction == "SHORT" and score >= 0:
        return False

    if snapshot.last_alert_at is not None:
        if datetime.now(timezone.utc) - snapshot.last_alert_at < timedelta(minutes=COOLDOWN_MINUTES):
            return False

    return True


def update_cooldown(snapshot: TickerSnapshot) -> TickerSnapshot:
    snapshot.last_alert_at = datetime.now(timezone.utc)
    return snapshot
