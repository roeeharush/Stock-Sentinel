from datetime import datetime, timedelta, timezone
from stock_sentinel.models import TickerSnapshot
from stock_sentinel.config import SENTIMENT_MIN_TWEETS, SENTIMENT_MIN_HEADLINES, COOLDOWN_MINUTES


def _twitter_ok(snapshot: TickerSnapshot) -> bool:
    s = snapshot.sentiment
    return s is not None and not s.failed and s.tweet_count >= SENTIMENT_MIN_TWEETS


def _news_ok(snapshot: TickerSnapshot) -> bool:
    n = snapshot.news_sentiment
    return n is not None and not n.failed and n.headline_count >= SENTIMENT_MIN_HEADLINES


def combined_sentiment_score(snapshot: TickerSnapshot) -> float:
    """Return 60/40 (news/twitter) weighted score with graceful degradation.

    Degradation rules:
    - Both available: 0.6 * news + 0.4 * twitter
    - Only news available: news score (100%)
    - Only twitter available: twitter score (100%)
    - Neither available: 0.0
    """
    t_ok = _twitter_ok(snapshot)
    n_ok = _news_ok(snapshot)

    if t_ok and n_ok:
        return 0.6 * snapshot.news_sentiment.score + 0.4 * snapshot.sentiment.score
    elif n_ok:
        return snapshot.news_sentiment.score
    elif t_ok:
        return snapshot.sentiment.score
    return 0.0


def should_alert(snapshot: TickerSnapshot) -> bool:
    t = snapshot.technical
    if t is None or t.direction == "NEUTRAL":
        return False

    if not _twitter_ok(snapshot) and not _news_ok(snapshot):
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
