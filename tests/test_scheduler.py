import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from stock_sentinel.models import (
    TickerSnapshot, SentimentResult, TechnicalSignal,
    NewsSentimentResult, RssSentimentResult, Alert,
)


def _make_sentiment(ticker, score=0.6, count=15, failed=False):
    return SentimentResult(
        ticker=ticker, score=score, tweet_count=count,
        scraped_at=datetime.now(timezone.utc), failed=failed,
    )


def _make_news(ticker, score=0.5, count=5, failed=False):
    return NewsSentimentResult(
        ticker=ticker,
        headlines=["headline"] * count,
        score=score,
        headline_count=count,
        fetched_at=datetime.now(timezone.utc),
        failed=failed,
    )


def _make_rss(ticker, score=0.4, count=5, failed=False):
    return RssSentimentResult(
        ticker=ticker,
        headlines=["rss headline"] * count,
        score=score,
        headline_count=count,
        fetched_at=datetime.now(timezone.utc),
        failed=failed,
    )


def _make_signal(ticker, direction="LONG"):
    return TechnicalSignal(
        ticker=ticker, rsi=27.0, ma_20=800.0, ma_50=780.0, atr=12.0,
        entry=810.0, stop_loss=792.0, take_profit=846.0,
        direction=direction, analyzed_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_async_cycle_happy_path():
    """Full happy path: scrape -> analyze -> filter -> alert fired for one ticker."""
    from stock_sentinel.scheduler import _async_cycle

    state = {}
    mock_page = AsyncMock()
    mock_df = MagicMock()

    with (
        patch("stock_sentinel.scheduler.scrape_sentiment",
              new_callable=AsyncMock,
              return_value=_make_sentiment("NVDA")) as mock_scrape,
        patch("stock_sentinel.scheduler.fetch_news_sentiment",
              return_value=_make_news("NVDA")) as mock_news,
        patch("stock_sentinel.scheduler.fetch_rss_sentiment",
              return_value=_make_rss("NVDA")) as mock_rss,
        patch("stock_sentinel.scheduler.fetch_ohlcv",
              return_value=mock_df) as mock_ohlcv,
        patch("stock_sentinel.scheduler.compute_signals",
              return_value=_make_signal("NVDA")) as mock_signals,
        patch("stock_sentinel.scheduler.should_alert",
              return_value=True) as mock_filter,
        patch("stock_sentinel.scheduler.generate_chart",
              return_value="/tmp/chart.png") as mock_chart,
        patch("stock_sentinel.scheduler.send_alert",
              new_callable=AsyncMock,
              return_value=42) as mock_notify,
        patch("stock_sentinel.scheduler.log_alert") as mock_log_alert,
        patch("stock_sentinel.scheduler.update_cooldown",
              side_effect=lambda s: s) as mock_cooldown,
    ):
        await _async_cycle(["NVDA"], state, mock_page)

    mock_scrape.assert_called_once()
    mock_news.assert_called_once()
    mock_rss.assert_called_once()
    mock_ohlcv.assert_called_once()
    mock_signals.assert_called_once()
    mock_filter.assert_called_once()
    mock_chart.assert_called_once()
    mock_notify.assert_called_once()
    mock_cooldown.assert_called_once()


@pytest.mark.asyncio
async def test_async_cycle_ticker_failure_continues():
    """When one ticker's fetch_ohlcv raises, the scheduler continues to the next ticker."""
    from stock_sentinel.scheduler import _async_cycle

    state = {}
    mock_page = AsyncMock()

    with (
        patch("stock_sentinel.scheduler.scrape_sentiment",
              new_callable=AsyncMock,
              return_value=_make_sentiment("NVDA")),
        patch("stock_sentinel.scheduler.fetch_news_sentiment",
              return_value=_make_news("NVDA")),
        patch("stock_sentinel.scheduler.fetch_rss_sentiment",
              return_value=_make_rss("NVDA")),
        patch("stock_sentinel.scheduler.fetch_ohlcv",
              side_effect=ValueError("no data")),
        patch("stock_sentinel.scheduler.send_alert",
              new_callable=AsyncMock) as mock_notify,
    ):
        # Should not raise even though fetch_ohlcv fails
        await _async_cycle(["NVDA", "AMZN"], state, mock_page)

    # No alert should have fired
    mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_circuit_breaker_triggers_after_n_failures():
    """Circuit breaker fires after SCRAPER_CIRCUIT_BREAKER_N consecutive scrape failures."""
    from stock_sentinel.scheduler import _async_cycle
    from stock_sentinel import config

    state = {}
    mock_page = AsyncMock()
    failed_sentiment = _make_sentiment("NVDA", failed=True)

    # Build a ticker list long enough to trigger the breaker
    tickers = ["T1", "T2", "T3", "T4"]

    with (
        patch("stock_sentinel.scheduler.scrape_sentiment",
              new_callable=AsyncMock,
              return_value=failed_sentiment),
        patch("stock_sentinel.scheduler.fetch_news_sentiment",
              return_value=_make_news("T1")),
        patch("stock_sentinel.scheduler.send_alert",
              new_callable=AsyncMock,
              return_value=42) as mock_notify,
    ):
        await _async_cycle(tickers, state, mock_page)

    # Circuit breaker admin ping must have fired
    assert mock_notify.call_count >= 1
    # Check the system alert was sent (ticker == "SYSTEM")
    call_args = mock_notify.call_args_list[0]
    alert_arg = call_args[0][0]
    assert alert_arg.ticker == "SYSTEM"


@pytest.mark.asyncio
async def test_async_cycle_unexpected_exception_continues():
    """When generate_chart raises unexpectedly, the scheduler catches it and continues."""
    from stock_sentinel.scheduler import _async_cycle

    state = {}
    mock_page = AsyncMock()

    with (
        patch("stock_sentinel.scheduler.scrape_sentiment",
              new_callable=AsyncMock,
              return_value=_make_sentiment("NVDA")),
        patch("stock_sentinel.scheduler.fetch_news_sentiment",
              return_value=_make_news("NVDA")),
        patch("stock_sentinel.scheduler.fetch_rss_sentiment",
              return_value=_make_rss("NVDA")),
        patch("stock_sentinel.scheduler.fetch_ohlcv",
              return_value=MagicMock()),
        patch("stock_sentinel.scheduler.compute_signals",
              return_value=_make_signal("NVDA")),
        patch("stock_sentinel.scheduler.should_alert",
              return_value=True),
        patch("stock_sentinel.scheduler.generate_chart",
              side_effect=RuntimeError("disk full")),
        patch("stock_sentinel.scheduler.send_alert",
              new_callable=AsyncMock) as mock_notify,
    ):
        # Must not raise
        await _async_cycle(["NVDA", "AMZN"], state, mock_page)

    # generate_chart raised, so no alert sent
    mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_async_cycle_logs_alert_on_success():
    """After a successful alert send, log_alert must be called once."""
    from stock_sentinel.scheduler import _async_cycle

    state = {}
    mock_page = AsyncMock()

    with (
        patch("stock_sentinel.scheduler.scrape_sentiment",
              new_callable=AsyncMock, return_value=_make_sentiment("NVDA")),
        patch("stock_sentinel.scheduler.fetch_news_sentiment",
              return_value=_make_news("NVDA")),
        patch("stock_sentinel.scheduler.fetch_rss_sentiment",
              return_value=_make_rss("NVDA")),
        patch("stock_sentinel.scheduler.fetch_ohlcv", return_value=MagicMock()),
        patch("stock_sentinel.scheduler.compute_signals",
              return_value=_make_signal("NVDA")),
        patch("stock_sentinel.scheduler.should_alert", return_value=True),
        patch("stock_sentinel.scheduler.generate_chart", return_value="/tmp/c.png"),
        patch("stock_sentinel.scheduler.send_alert",
              new_callable=AsyncMock, return_value=42),
        patch("stock_sentinel.scheduler.log_alert") as mock_log_alert,
        patch("stock_sentinel.scheduler.update_cooldown", side_effect=lambda s: s),
    ):
        await _async_cycle(["NVDA"], state, mock_page)

    mock_log_alert.assert_called_once()
