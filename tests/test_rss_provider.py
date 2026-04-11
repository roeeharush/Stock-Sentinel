import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from stock_sentinel.rss_provider import fetch_rss_sentiment, _score_headlines
from stock_sentinel.models import RssSentimentResult

_SAMPLE_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>NVDA surges on AI chip demand</title></item>
  <item><title>Analysts upgrade NVDA to strong buy</title></item>
  <item><title>NVDA rallies after earnings beat</title></item>
</channel></rss>"""


def test_score_headlines_bullish():
    assert _score_headlines(["NVDA surges on AI rally", "analysts upgrade to buy"]) > 0.0


def test_score_headlines_bearish():
    assert _score_headlines(["NVDA crashes after miss", "downgrade to sell"]) < 0.0


def test_score_headlines_empty():
    assert _score_headlines([]) == 0.0


def test_fetch_rss_returns_result():
    import io
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__ = lambda s: io.BytesIO(_SAMPLE_RSS)
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        result = fetch_rss_sentiment("NVDA")
    assert isinstance(result, RssSentimentResult)
    assert result.failed is False
    assert result.headline_count == 3
    assert result.score > 0.0


def test_fetch_rss_failed_on_exception():
    with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = fetch_rss_sentiment("NVDA")
    assert result.failed is True
    assert result.score == 0.0
