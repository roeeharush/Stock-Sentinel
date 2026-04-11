from datetime import datetime, timedelta, timezone
from stock_sentinel.models import (
    TickerSnapshot, SentimentResult, TechnicalSignal,
    NewsSentimentResult, RssSentimentResult,
)
from stock_sentinel.signal_filter import should_alert, update_cooldown, combined_sentiment_score


def _snap(
    direction="LONG",
    twitter_score=0.6, twitter_count=15, twitter_failed=False,
    news_score=0.5, news_count=5, news_failed=False,
    rss_score=0.4, rss_count=5, rss_failed=False,
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
        rss_sentiment=RssSentimentResult(
            ticker="NVDA", headlines=["rss headline"] * rss_count, score=rss_score,
            headline_count=rss_count, fetched_at=now, failed=rss_failed,
        ),
        technical=TechnicalSignal(
            ticker="NVDA", rsi=25.0, ma_20=800.0, ma_50=780.0, atr=12.0,
            entry=810.0, stop_loss=792.0, take_profit=846.0,
            direction=direction, analyzed_at=now,
            technical_score=80,
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


def test_all_sources_failed_no_alert():
    assert should_alert(_snap(twitter_failed=True, news_failed=True, rss_failed=True)) is False


def test_twitter_failed_fallback_to_rss_news():
    snap = _snap(twitter_failed=True, news_score=0.5, news_count=5, rss_score=0.4, rss_count=5)
    assert should_alert(snap) is True


def test_rss_failed_fallback_to_news_twitter():
    snap = _snap(rss_failed=True, news_score=0.5, news_count=5, twitter_score=0.6, twitter_count=15)
    assert should_alert(snap) is True


def test_news_failed_fallback_to_rss_twitter():
    snap = _snap(news_failed=True, rss_score=0.5, rss_count=5, twitter_score=0.6, twitter_count=15)
    assert should_alert(snap) is True


def test_sentiment_disagrees_no_alert():
    snap = _snap(twitter_score=-0.8, news_score=-0.6, rss_score=-0.5)
    assert should_alert(snap) is False


def test_cooldown_active_no_alert():
    assert should_alert(_snap(last_alert_minutes_ago=30)) is False


def test_cooldown_expired_alerts():
    assert should_alert(_snap(last_alert_minutes_ago=130)) is True


def test_combined_score_40_40_20_weighting():
    # 0.40*0.4 + 0.40*0.5 + 0.20*0.6 = 0.16 + 0.20 + 0.12 = 0.48
    snap = _snap(rss_score=0.4, news_score=0.5, twitter_score=0.6)
    score = combined_sentiment_score(snap)
    assert abs(score - 0.48) < 0.001


def test_low_tweet_count_falls_back_to_rss_and_news():
    # twitter_count=4 -> twitter excluded -> rss 40% + news 40% -> normalized 50/50
    # score = (0.40*0.4 + 0.40*0.4) / 0.80 = 0.4
    snap = _snap(twitter_count=4, twitter_score=0.9, rss_score=0.4, news_score=0.4)
    score = combined_sentiment_score(snap)
    assert abs(score - 0.4) < 0.001


def test_rss_failed_normalized_score():
    # rss fails -> news 40% + twitter 20% -> total weight 0.60
    # score = (0.40*0.5 + 0.20*0.6) / 0.60 = 0.32/0.60 ~= 0.5333
    snap = _snap(rss_failed=True, news_score=0.5, news_count=5, twitter_score=0.6, twitter_count=15)
    score = combined_sentiment_score(snap)
    assert abs(score - (0.32 / 0.60)) < 0.001


def test_update_cooldown_stamps_now():
    snap = _snap()
    updated = update_cooldown(snap)
    assert updated.last_alert_at is not None
    delta = datetime.now(timezone.utc) - updated.last_alert_at
    assert delta.total_seconds() < 2


def test_low_technical_score_no_alert():
    """TechnicalScore below threshold suppresses alert regardless of sentiment."""
    snap = _snap()
    snap.technical.technical_score = 40  # below TECHNICAL_SCORE_MIN=60
    assert should_alert(snap) is False


def test_technical_score_at_threshold_alerts():
    """TechnicalScore exactly at threshold allows alert."""
    snap = _snap()
    snap.technical.technical_score = 60  # exactly at threshold
    assert should_alert(snap) is True
