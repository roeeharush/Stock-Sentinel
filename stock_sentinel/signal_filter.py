from datetime import datetime, timedelta, timezone
from stock_sentinel.models import TickerSnapshot
from stock_sentinel.config import SENTIMENT_MIN_TWEETS, SENTIMENT_MIN_HEADLINES, COOLDOWN_MINUTES


def combined_sentiment_score(snapshot: TickerSnapshot) -> float:
    """Return 60/40 (news/twitter) weighted score with graceful degradation.

    Degradation rules:
    - Both available: 0.6 * news + 0.4 * twitter
    - Only news available: news score (100%)
    - Only twitter available: twitter score (100%)
    - Neither available: 0.0
    """
    s = snapshot.sentiment
    n = snapshot.news_sentiment

    twitter_ok = (
        s is not None
        and not s.failed
        and s.tweet_count >= SENTIMENT_MIN_TWEETS
    )
    news_ok = (
        n is not None
        and not n.failed
        and n.headline_count >= SENTIMENT_MIN_HEADLINES
    )

    if twitter_ok and news_ok:
        return 0.6 * n.score + 0.4 * s.score
    elif news_ok:
        return n.score
    elif twitter_ok:
        return s.score
    return 0.0


def should_alert(snapshot: TickerSnapshot) -> bool:
    t = snapshot.technical
    if t is None or t.direction == "NEUTRAL":
        return False

    s = snapshot.sentiment
    n = snapshot.news_sentiment
    twitter_ok = (
        s is not None
        and not s.failed
        and s.tweet_count >= SENTIMENT_MIN_TWEETS
    )
    news_ok = (
        n is not None
        and not n.failed
        and n.headline_count >= SENTIMENT_MIN_HEADLINES
    )
    if not twitter_ok and not news_ok:
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
