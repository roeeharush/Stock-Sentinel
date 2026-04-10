import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from stock_sentinel.scraper import scrape_sentiment, _score_texts
from stock_sentinel.models import SentimentResult

def test_score_texts_bullish():
    assert _score_texts(["nvda breakout bullish calls", "buy the dip rally"]) > 0.0

def test_score_texts_bearish():
    assert _score_texts(["nvda dump puts crash", "sell short bearish"]) < 0.0

def test_score_texts_empty_returns_zero():
    assert _score_texts([]) == 0.0

@pytest.mark.asyncio
async def test_scrape_sentiment_failed_on_exception():
    mock_page = AsyncMock()
    mock_page.goto.side_effect = Exception("timeout")
    result = await scrape_sentiment("NVDA", mock_page)
    assert isinstance(result, SentimentResult)
    assert result.failed is True
    assert result.ticker == "NVDA"

@pytest.mark.asyncio
async def test_scrape_sentiment_low_count_not_failed():
    mock_page = AsyncMock()
    mock_tweet = AsyncMock()
    mock_tweet.inner_text = AsyncMock(return_value="bullish nvda")
    mock_page.query_selector_all = AsyncMock(return_value=[mock_tweet] * 5)
    result = await scrape_sentiment("NVDA", mock_page)
    assert result.failed is False
    assert result.tweet_count == 5
