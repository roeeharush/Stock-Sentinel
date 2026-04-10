import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from stock_sentinel.news_scraper import fetch_news_sentiment, _score_headlines
from stock_sentinel.models import NewsSentimentResult


def test_score_headlines_bullish():
    headlines = ["NVDA surges on strong earnings beat", "Analysts upgrade NVDA to buy"]
    assert _score_headlines(headlines) > 0.0


def test_score_headlines_bearish():
    headlines = ["NVDA crashes after guidance cut", "Sell-off continues as NVDA misses estimates"]
    assert _score_headlines(headlines) < 0.0


def test_score_headlines_empty():
    assert _score_headlines([]) == 0.0


def test_fetch_news_returns_result():
    mock_news = [
        {"title": "NVDA rallies on AI demand"},
        {"title": "NVDA stock climbs higher"},
        {"title": "Bullish outlook for NVDA"},
    ]
    with patch("stock_sentinel.news_scraper.yf.Ticker") as MockTicker:
        MockTicker.return_value.news = mock_news
        result = fetch_news_sentiment("NVDA")
    assert isinstance(result, NewsSentimentResult)
    assert result.ticker == "NVDA"
    assert result.failed is False
    assert len(result.headlines) == 3
    assert result.score > 0.0
    assert result.headline_count == 3


def test_fetch_news_failed_on_exception():
    with patch("stock_sentinel.news_scraper.yf.Ticker") as MockTicker:
        MockTicker.side_effect = Exception("network error")
        result = fetch_news_sentiment("NVDA")
    assert result.failed is True
    assert result.ticker == "NVDA"
    assert result.score == 0.0
