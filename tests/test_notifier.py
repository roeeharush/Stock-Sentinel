import os
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from stock_sentinel.notifier import (
    build_message, generate_chart, send_alert,
    build_daily_report, send_daily_report,
    build_news_flash_message, send_news_flash,
)
from stock_sentinel.visualizer import generate_chart as visualizer_generate_chart
from stock_sentinel.models import Alert, NewsFlash, TechnicalSignal


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
    # Ticker and price levels must appear
    for fragment in ["NVDA", "810", "792", "846", "RSI"]:
        assert fragment in msg, f"Missing '{fragment}' in message"
    # Direction must appear
    assert "קניה" in msg or "LONG" in msg
    # New format: percentage markers must appear
    assert "%" in msg


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
    assert "%" in msg
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
    # New format: "סיכום אנליסט" section (Task 17.2)
    assert "סיכום אנליסט" in msg
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


from stock_sentinel.notifier import send_trade_update


@pytest.mark.asyncio
async def test_send_trade_update_sl():
    trade = {"ticker": "NVDA", "telegram_message_id": 42}
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(return_value=MagicMock())
        result = await send_trade_update(trade, "SL", 878.0, "token", "chat")
    assert result is True
    call_kwargs = mock_instance.send_message.call_args.kwargs
    assert call_kwargs.get("reply_to_message_id") == 42
    assert "סטופ" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_trade_update_tp1():
    trade = {"ticker": "NVDA", "telegram_message_id": None}
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(return_value=MagicMock())
        result = await send_trade_update(trade, "TP1", 913.5, "token", "chat")
    assert result is True
    assert "reply_to_message_id" not in mock_instance.send_message.call_args.kwargs
    assert "יעד 1" in mock_instance.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_send_trade_update_tp3_status():
    trade = {"ticker": "NVDA", "telegram_message_id": 10}
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(return_value=MagicMock())
        await send_trade_update(trade, "TP3", 945.0, "token", "chat")
    assert "מקסימלי" in mock_instance.send_message.call_args.kwargs["text"]


# ── Task 16: Expert Tier notifier tests ──────────────────────────────────────

def test_build_message_institutional_score():
    """When institutional_score is set it appears in the message as X/10."""
    alert, _ = _alert()
    alert_with_score = Alert(
        ticker="NVDA", direction="LONG", entry=810.0,
        stop_loss=792.0, take_profit=846.0, rsi=27.0,
        sentiment_score=0.54,
        institutional_score=8.5,
    )
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert_with_score, [])
    assert "8.5/10" in msg
    assert "סנטימנט מוסדי חזק" in msg


def test_build_message_pct_targets():
    """Percentage change values appear in the trade level section."""
    alert_pct = Alert(
        ticker="NVDA", direction="LONG", entry=200.0,
        stop_loss=190.0, take_profit=220.0, rsi=27.0,
        sentiment_score=0.5,
        take_profit_1=210.0, take_profit_3=240.0,
        pct_sl=-5.0, pct_tp1=5.0, pct_tp2=10.0, pct_tp3=20.0,
    )
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert_pct, [])
    assert "-5.0%" in msg
    assert "+5.0%" in msg
    assert "+10.0%" in msg
    assert "+20.0%" in msg


def test_build_message_pivot_levels():
    """Pivot R1/R2/S1/S2 appear in the technical metrics section."""
    alert_piv = Alert(
        ticker="NVDA", direction="LONG", entry=810.0,
        stop_loss=792.0, take_profit=846.0, rsi=27.0,
        sentiment_score=0.5,
        pivot_r1=820.0, pivot_r2=835.0, pivot_s1=800.0, pivot_s2=785.0,
    )
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert_piv, [])
    assert "820.00" in msg
    assert "800.00" in msg


def test_build_message_rsi_divergence():
    """RSI bullish divergence label appears in the message."""
    alert_div = Alert(
        ticker="NVDA", direction="LONG", entry=810.0,
        stop_loss=792.0, take_profit=846.0, rsi=27.0,
        sentiment_score=0.5,
        rsi_divergence="bullish",
    )
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert_div, [])
    assert "דיברגנס שורי" in msg


def test_build_message_analyst_summary_vwap():
    """Analyst summary includes VWAP reference when close to entry."""
    alert_vwap = Alert(
        ticker="NVDA", direction="LONG", entry=810.0,
        stop_loss=792.0, take_profit=846.0, rsi=27.0,
        sentiment_score=0.5,
        vwap=808.0,  # within 2% of entry — triggers the VWAP summary line
    )
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert_vwap, [])
    assert "VWAP" in msg
    assert "סיכום אנליסט" in msg


def test_build_message_scanner_header():
    """scanner_hit=True produces '🔍 מנייה חמה' header instead of '🎯 איתות'."""
    alert_scan = Alert(
        ticker="SOFI", direction="LONG", entry=10.0,
        stop_loss=9.5, take_profit=11.0, rsi=27.0,
        sentiment_score=0.5,
        scanner_hit=True,
    )
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert_scan, [])
    assert "מנייה חמה" in msg
    assert "🔍" in msg
    assert "SOFI" in msg


def test_build_message_watchlist_header():
    """scanner_hit=False (default) produces '🎯 איתות למסחר' header."""
    alert_watch = Alert(
        ticker="NVDA", direction="LONG", entry=810.0,
        stop_loss=792.0, take_profit=846.0, rsi=27.0,
        sentiment_score=0.5,
    )
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert_watch, [])
    assert "🎯" in msg
    assert "איתות למסחר" in msg


def test_build_message_risk_reward_displayed():
    """When risk_reward is set, the R/R ratio appears in the message."""
    alert_rr = Alert(
        ticker="NVDA", direction="LONG", entry=200.0,
        stop_loss=190.0, take_profit=220.0, rsi=27.0,
        sentiment_score=0.5,
        risk_reward=2.0,
    )
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert_rr, [])
    assert "2.0" in msg


def test_build_message_ma_ribbon_golden_cross():
    """Golden Cross triggers MA ribbon paragraph in analyst summary."""
    alert_gc = Alert(
        ticker="NVDA", direction="LONG", entry=810.0,
        stop_loss=792.0, take_profit=846.0, rsi=27.0,
        sentiment_score=0.5,
        golden_cross=True,
    )
    with patch("stock_sentinel.notifier.translate_to_hebrew", side_effect=lambda x: x):
        msg = build_message(alert_gc, [])
    assert "Golden Cross" in msg


def test_visualizer_generate_chart_creates_png():
    """visualizer.generate_chart produces a valid PNG file."""
    from stock_sentinel.models import TechnicalSignal
    sig = TechnicalSignal(
        ticker="NVDA", rsi=27.0, ma_20=800.0, ma_50=780.0, atr=12.0,
        entry=810.0, stop_loss=792.0, take_profit=846.0,
        direction="LONG", analyzed_at=datetime.now(timezone.utc),
        take_profit_1=828.0, take_profit_3=870.0,
        fib_618=805.0, fib_65=802.0, poc_price=807.0,
    )
    path = visualizer_generate_chart("NVDA", _df(), sig)
    assert os.path.exists(path)
    assert path.endswith(".png")
    os.remove(path)


# ── Task 19: News Flash notifier tests ───────────────────────────────────────

def _flash(reaction="bullish", url="https://example.com/story"):
    return NewsFlash(
        ticker="NVDA",
        title="NVDA beats earnings with strong rally",
        summary="NVDA beats earnings. מגמה עולה עם RSI 42 ואיתות LONG.",
        url=url,
        source="Reuters",
        sentiment_score=0.8,
        catalyst_keywords=["earnings", "beat"],
        reaction=reaction,
        published_at=datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc),
        item_id="test-001",
    )


def test_build_news_flash_message_bullish_header():
    msg = build_news_flash_message(_flash("bullish"))
    assert "📢" in msg
    assert "מבזק חדשות מתפרצות" in msg
    assert "NVDA" in msg


def test_build_news_flash_message_bullish_reaction():
    msg = build_news_flash_message(_flash("bullish"))
    assert "🚀" in msg
    assert "עלייה חזקה" in msg


def test_build_news_flash_message_bearish_reaction():
    flash = _flash("bearish")
    flash.sentiment_score = -0.8
    msg = build_news_flash_message(flash)
    assert "⚠️" in msg
    assert "ירידה חדה" in msg


def test_build_news_flash_message_contains_title():
    msg = build_news_flash_message(_flash())
    assert "NVDA beats earnings" in msg


def test_build_news_flash_message_contains_summary():
    msg = build_news_flash_message(_flash())
    assert "מגמה עולה" in msg


def test_build_news_flash_message_contains_keywords():
    msg = build_news_flash_message(_flash())
    assert "earnings" in msg


def test_build_news_flash_message_contains_source_link():
    msg = build_news_flash_message(_flash(url="https://example.com/story"))
    assert "Reuters" in msg
    assert "https://example.com/story" in msg


def test_build_news_flash_message_no_url_shows_source():
    flash = _flash(url="")
    msg = build_news_flash_message(flash)
    assert "Reuters" in msg


def test_build_news_flash_message_timestamp():
    msg = build_news_flash_message(_flash())
    assert "15/01/2025" in msg


@pytest.mark.asyncio
async def test_send_news_flash_success():
    flash = _flash()
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(return_value=MagicMock())
        result = await send_news_flash(flash, "fake_token", "fake_chat")
    assert result is True
    call_kwargs = mock_instance.send_message.call_args.kwargs
    assert "מבזק חדשות" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_news_flash_failure_returns_false():
    from telegram.error import TelegramError
    flash = _flash()
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(side_effect=TelegramError("fail"))
        result = await send_news_flash(flash, "fake_token", "fake_chat")
    assert result is False
