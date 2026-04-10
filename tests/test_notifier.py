import os
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from stock_sentinel.notifier import build_message, generate_chart, send_alert
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
    msg = build_message(alert, headlines)
    for fragment in ["NVDA", "LONG", "810", "792", "846", "RSI", "0.54", "0.60", "0.50"]:
        assert fragment in msg, f"Missing '{fragment}' in message"


def test_build_message_contains_headlines():
    alert, headlines = _alert(["NVDA surges higher", "Upgrade to buy"])
    msg = build_message(alert, headlines)
    assert "NVDA surges higher" in msg
    assert "Upgrade to buy" in msg


def test_build_message_no_headlines():
    alert, _ = _alert()
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
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_bot_instance = AsyncMock()
        MockBot.return_value = mock_bot_instance
        mock_bot_instance.send_message = AsyncMock(return_value=MagicMock())
        result = await send_alert(alert, headlines, "fake_token", "fake_chat")
    assert result is True
    mock_bot_instance.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_alert_returns_false_on_failure():
    from telegram.error import TelegramError
    alert, headlines = _alert()
    with patch("stock_sentinel.notifier.Bot") as MockBot, \
         patch("stock_sentinel.notifier.asyncio.sleep", new_callable=AsyncMock):
        mock_bot_instance = AsyncMock()
        MockBot.return_value = mock_bot_instance
        mock_bot_instance.send_message = AsyncMock(side_effect=TelegramError("fail"))
        mock_bot_instance.send_photo = AsyncMock(side_effect=TelegramError("fail"))
        result = await send_alert(alert, headlines, "fake_token", "fake_chat")
    assert result is False
