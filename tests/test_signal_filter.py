from datetime import datetime, timedelta, timezone
from stock_sentinel.models import TickerSnapshot, SentimentResult, TechnicalSignal, NewsSentimentResult
from stock_sentinel.signal_filter import should_alert, update_cooldown, combined_sentiment_score


def _snap(
    direction="LONG",
    twitter_score=0.6, twitter_count=15, twitter_failed=False,
    news_score=0.5, news_count=5, news_failed=False,
    last_alert_minutes_ago=None,
):
    now = datetime.now(timezone.utc)
    return TickerSnapshot(
        ticker="NVDA",
        sentiment=SentimentResult(
            ticker="NVDA", score=twitter_score, tweet_count=twitter_count,
            scraped_at=now, failed=twitter_failed,
        ),
        news_sentiment=NewsSentimentResult(
            ticker="NVDA", headlines=["headline"] * news_count, score=news_score,
            headline_count=news_count, fetched_at=now, failed=news_failed,
        ),
        technical=TechnicalSignal(
            ticker="NVDA", rsi=25.0, ma_20=800.0, ma_50=780.0, atr=12.0,
            entry=810.0, stop_loss=792.0, take_profit=846.0,
            direction=direction, analyzed_at=now,
        ),
        last_alert_at=(
            now - timedelta(minutes=last_alert_minutes_ago)
            if last_alert_minutes_ago else None
        ),
    )


def test_valid_long_alerts():
    assert should_alert(_snap()) is True


def test_neutral_direction_no_alert():
    assert should_alert(_snap(direction="NEUTRAL")) is False


def test_both_sources_failed_no_alert():
    assert should_alert(_snap(twitter_failed=True, news_failed=True)) is False


def test_twitter_failed_fallback_to_news():
    # Twitter fails, news is positive -> LONG should still fire
    snap = _snap(twitter_failed=True, news_score=0.5, news_count=5)
    assert should_alert(snap) is True


def test_news_failed_fallback_to_twitter():
    # News fails, twitter is positive -> LONG should still fire
    snap = _snap(news_failed=True, twitter_score=0.6, twitter_count=15)
    assert should_alert(snap) is True


def test_sentiment_disagrees_no_alert():
    # LONG direction but combined score is negative
    snap = _snap(twitter_score=-0.8, news_score=-0.6)
    assert should_alert(snap) is False


def test_cooldown_active_no_alert():
    assert should_alert(_snap(last_alert_minutes_ago=30)) is False


def test_cooldown_expired_alerts():
    assert should_alert(_snap(last_alert_minutes_ago=130)) is True


def test_combined_score_60_40_weighting():
    # With both sources available: 0.6 * 0.5 + 0.4 * 0.6 = 0.3 + 0.24 = 0.54
    snap = _snap(twitter_score=0.6, news_score=0.5)
    score = combined_sentiment_score(snap)
    assert abs(score - 0.54) < 0.001


def test_low_tweet_count_falls_back_to_news():
    # Below SENTIMENT_MIN_TWEETS=10 -> twitter excluded -> 100% news weight
    snap = _snap(twitter_count=4, twitter_score=0.9, news_score=0.4)
    score = combined_sentiment_score(snap)
    assert abs(score - 0.4) < 0.001


def test_update_cooldown_stamps_now():
    snap = _snap()
    updated = update_cooldown(snap)
    assert updated.last_alert_at is not None
    delta = datetime.now(timezone.utc) - updated.last_alert_at
    assert delta.total_seconds() < 2
