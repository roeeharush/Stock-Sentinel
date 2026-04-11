import os
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from stock_sentinel.notifier import build_message, generate_chart, send_alert, build_daily_report, send_daily_report
from stock_sentinel.models import Alert, TechnicalSignal


def _signal():
    return TechnicalSignal(
        ticker="NVDA", rsi=27.0, ma_20=800.0, ma_50=780.0, atr=12.0,
        entry=810.0, stop_loss=792.0, take_profit=846.0,
        direction="LONG", analyzed_at=datetime.now(timezone.utc),
    )


def _df():
    np.random.seed(1)
    close = 800 + np.cumsum(np.random.randn(60))
    return pd.DataFrame({
        "Open": close - 0.5, "High": close + 1.0,
        "Low": close - 1.0, "Close": close,
        "Volume": np.random.randint(1_000_000, 5_000_000, 60),
    }, index=pd.date_range("2025-01-01", periods=60, freq="B"))


def _alert(headlines=None):
    return Alert(
        ticker="NVDA", direction="LONG", entry=810.0,
        stop_loss=792.0, take_profit=846.0, rsi=27.0,
        sentiment_score=0.54, twitter_score=0.6, news_score=0.5,
        chart_path=None,
    ), (headlines or ["NVDA rallies on AI demand", "Analysts upgrade NVDA"])


def test_build_message_contains_required_fields():
    alert, headlines = _alert()
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert, headlines)
    # ticker and numeric values must appear
    for fragment in ["NVDA", "810", "792", "846", "RSI", "0.54", "0.60", "0.50"]:
        assert fragment in msg, f"Missing '{fragment}' in message"
    # Hebrew direction words must appear
    assert "קניה" in msg or "LONG" in msg


def test_build_message_contains_headlines():
    alert, headlines = _alert(["NVDA surges higher", "Upgrade to buy"])
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert, headlines)
    assert "NVDA surges higher" in msg
    assert "Upgrade to buy" in msg


def test_build_message_no_headlines():
    alert, _ = _alert()
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert, [])
    assert "NVDA" in msg
    assert "RSI" in msg
    assert "0.54" in msg
    assert "Top Headlines" not in msg


def test_generate_chart_creates_png():
    path = generate_chart("NVDA", _df(), _signal())
    assert os.path.exists(path)
    assert path.endswith(".png")
    os.remove(path)


@pytest.mark.asyncio
async def test_send_alert_returns_true_on_success():
    alert, headlines = _alert()
    with patch("stock_sentinel.notifier.Bot") as MockBot, \
         patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        mock_bot_instance = AsyncMock()
        MockBot.return_value = mock_bot_instance
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        mock_bot_instance.send_message = AsyncMock(return_value=mock_msg)
        result = await send_alert(alert, headlines, "fake_token", "fake_chat")
    assert result == 42
    mock_bot_instance.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_alert_returns_false_on_failure():
    from telegram.error import TelegramError
    alert, headlines = _alert()
    with patch("stock_sentinel.notifier.Bot") as MockBot, \
         patch("stock_sentinel.notifier.asyncio.sleep", new_callable=AsyncMock), \
         patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        mock_bot_instance = AsyncMock()
        MockBot.return_value = mock_bot_instance
        mock_bot_instance.send_message = AsyncMock(side_effect=TelegramError("fail"))
        mock_bot_instance.send_photo = AsyncMock(side_effect=TelegramError("fail"))
        result = await send_alert(alert, headlines, "fake_token", "fake_chat")
    assert result is None


def test_build_daily_report_no_alerts():
    msg = build_daily_report({"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "top_factors": []})
    assert "לא נשלחו" in msg


def test_build_daily_report_with_stats():
    stats = {
        "total": 5, "wins": 4, "losses": 1, "win_rate": 0.8,
        "top_factors": ["EMA 200 Trend", "Volume Spike"],
    }
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_daily_report(stats)
    assert "5" in msg
    assert "4" in msg
    assert "80%" in msg
    assert "EMA 200 Trend" in msg
    assert "Volume Spike" in msg


def test_build_message_horizon_section():
    alert, headlines = _alert()
    alert_with_horizon = Alert(
        ticker="NVDA", direction="LONG", entry=810.0,
        stop_loss=792.0, take_profit=846.0, rsi=27.0,
        sentiment_score=0.54, twitter_score=0.6, news_score=0.5,
        chart_path=None,
        horizon="SHORT_TERM",
        horizon_reason="המניה מציגה פריצת ווליום — אות מומנטום לטווח קצר.",
    )
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert_with_horizon, [])
    assert "טווח קצר" in msg
    assert "הסבר האסטרטגיה" in msg
    assert "פריצת ווליום" in msg


@pytest.mark.asyncio
async def test_send_daily_report_success():
    stats = {"total": 3, "wins": 2, "losses": 1, "win_rate": 2/3, "top_factors": []}
    with patch("stock_sentinel.notifier.Bot") as MockBot, \
         patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(return_value=MagicMock())
        result = await send_daily_report(stats, "fake_token", "fake_chat")
    assert result is True
    mock_instance.send_message.assert_called_once()
