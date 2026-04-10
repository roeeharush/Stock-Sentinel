from datetime import datetime, timezone
from stock_sentinel.models import (
    SentimentResult, TechnicalSignal, TickerSnapshot, Alert, NewsSentimentResult
)


def test_sentiment_result_defaults():
    s = SentimentResult(ticker="NVDA", score=0.5, tweet_count=15,
                        scraped_at=datetime.now(timezone.utc))
    assert s.failed is False
    assert s.source == "x"


def test_technical_signal_fields():
    t = TechnicalSignal(
        ticker="NVDA", rsi=28.0, ma_20=800.0, ma_50=780.0, atr=12.5,
        entry=810.0, stop_loss=791.25, take_profit=847.5,
        direction="LONG", analyzed_at=datetime.now(timezone.utc)
    )
    assert t.direction == "LONG"


def test_ticker_snapshot_defaults():
    snap = TickerSnapshot(ticker="AMZN")
    assert snap.sentiment is None
    assert snap.last_alert_at is None


def test_alert_construction():
    a = Alert(
        ticker="NVDA", direction="LONG", entry=810.0,
        stop_loss=791.25, take_profit=847.5, rsi=28.0,
        sentiment_score=0.5, chart_path=None,
        generated_at=datetime.now(timezone.utc),
    )
    assert a.ticker == "NVDA"
    assert a.chart_path is None


def test_technical_signal_direction_literals():
    """Downstream signal_filter compares direction to string literals."""
    now = datetime.now(timezone.utc)
    for d in ("LONG", "SHORT", "NEUTRAL"):
        t = TechnicalSignal(
            ticker="X", rsi=50.0, ma_20=100.0, ma_50=100.0, atr=1.0,
            entry=100.0, stop_loss=99.0, take_profit=103.0,
            direction=d, analyzed_at=now,
        )
        assert t.direction == d


def test_ticker_snapshot_has_news_sentiment():
    snap = TickerSnapshot(ticker="NVDA")
    assert snap.news_sentiment is None
    ns = NewsSentimentResult(
        ticker="NVDA", headlines=["NVDA beats earnings"],
        score=0.5, headline_count=1, fetched_at=datetime.now(timezone.utc)
    )
    snap.news_sentiment = ns
    assert snap.news_sentiment.score == 0.5
