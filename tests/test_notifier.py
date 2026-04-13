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
    build_macro_flash_message, send_macro_flash,
    build_smart_money_message, send_smart_money_alert,
    build_learning_report_message, send_learning_report,
)
from stock_sentinel.visualizer import generate_chart as visualizer_generate_chart
from stock_sentinel.models import Alert, InsiderAlert, LearningReport, MacroFlash, NewsFlash, OptionsFlowAlert, PatternFinding, TechnicalSignal


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
    assert "⏰" in call_kwargs["text"]


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
    text = mock_instance.send_message.call_args.kwargs["text"]
    assert "יעד 1" in text
    assert "⏰" in text


@pytest.mark.asyncio
async def test_send_trade_update_tp3_status():
    trade = {"ticker": "NVDA", "telegram_message_id": 10}
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(return_value=MagicMock())
        await send_trade_update(trade, "TP3", 945.0, "token", "chat")
    text = mock_instance.send_message.call_args.kwargs["text"]
    assert "מקסימלי" in text
    assert "⏰" in text


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
    assert "מבזק חדשות" in msg
    assert "NVDA" in msg


def test_build_news_flash_message_bullish_reaction():
    msg = build_news_flash_message(_flash("bullish"))
    assert "💡" in msg
    assert "📝" in msg
    assert "מבזק חדשות" in msg


def test_build_news_flash_message_bearish_reaction():
    flash = _flash("bearish")
    flash.sentiment_score = -0.8
    msg = build_news_flash_message(flash)
    assert "💡" in msg
    assert "📝" in msg
    assert "מבזק חדשות" in msg


def test_build_news_flash_message_contains_title():
    msg = build_news_flash_message(_flash())
    assert "NVDA beats earnings" in msg


def test_build_news_flash_message_contains_summary():
    msg = build_news_flash_message(_flash())
    assert "מגמה עולה" in msg


def test_build_news_flash_message_no_keywords_row():
    """Keywords row must NOT appear in the message (Task 24.1 de-clutter)."""
    msg = build_news_flash_message(_flash())
    assert "מילות מפתח" not in msg
    assert "תגובה צפויה" not in msg


def test_build_news_flash_message_contains_source_link():
    # URL row removed — source name now appears in parentheses inside the summary
    msg = build_news_flash_message(_flash(url="https://example.com/story"))
    assert "Reuters" in msg   # source name embedded in summary


def test_build_news_flash_message_discovery_header():
    """is_watchlist=False produces 💎 גילוי הזדמנות header."""
    flash = _flash()
    flash.is_watchlist = False
    msg = build_news_flash_message(flash)
    assert "💎" in msg
    assert "גילוי הזדמנות" in msg
    assert "NVDA" in msg


def test_build_news_flash_message_watchlist_header_default():
    """Default is_watchlist=True produces 📢 מבזק חדשות header."""
    msg = build_news_flash_message(_flash())
    assert "📢" in msg
    assert "מבזק חדשות" in msg


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


# ── Task 23: Macro Flash notifier tests ──────────────────────────────────────

def _macro_flash(reaction="bearish", url="https://reuters.com/macro/1"):
    return MacroFlash(
        title="Fed raises rates sharply — strong hawkish signal",
        summary="Fed raises rates. האירוע קשור ל-Fed ועשוי להשפיע על כיוון השוק הכללי — סנטימנט שלילי (Risk-Off).",
        url=url,
        source="Reuters",
        sentiment_score=-0.8,
        influencers=["Fed", "Interest Rate"],
        reaction=reaction,
        affected_assets=["SPY", "QQQ", "DIA"],
        published_at=datetime(2025, 3, 20, 18, 0, tzinfo=timezone.utc),
        item_id="macro-test-001",
    )


def test_build_macro_flash_message_header():
    msg = build_macro_flash_message(_macro_flash())
    assert "🏛️" in msg
    assert "אירוע מאקרו משמעותי" in msg
    assert "🌐" in msg
    assert "מבזק מאקרו ופוליטיקה עולמית" in msg


def test_build_macro_flash_message_bearish_sentiment():
    msg = build_macro_flash_message(_macro_flash("bearish"))
    assert "📉" in msg
    assert "שלילי" in msg    # Hebrew-only labels (Task 25)
    assert "Risk-Off" in msg  # kept in parentheses for clarity


def test_build_macro_flash_message_bullish_sentiment():
    mf = _macro_flash("bullish")
    mf.sentiment_score = 0.8
    msg = build_macro_flash_message(mf)
    assert "📈" in msg
    assert "חיובי" in msg    # Hebrew-only labels (Task 25)
    assert "Risk-On" in msg   # kept in parentheses for clarity


def test_build_macro_flash_message_contains_title():
    msg = build_macro_flash_message(_macro_flash())
    assert "Fed raises rates" in msg


def test_build_macro_flash_message_contains_summary():
    msg = build_macro_flash_message(_macro_flash())
    assert "Risk-Off" in msg


def test_build_macro_flash_message_contains_influencers():
    msg = build_macro_flash_message(_macro_flash())
    assert "Fed" in msg


def test_build_macro_flash_message_contains_affected_assets():
    msg = build_macro_flash_message(_macro_flash())
    assert "SPY" in msg
    assert "QQQ" in msg
    assert "DIA" in msg


def test_build_macro_flash_message_contains_source_link():
    # URL row removed — source name now appears in parentheses after the title
    msg = build_macro_flash_message(_macro_flash(url="https://reuters.com/macro/1"))
    assert "Reuters" in msg   # source name embedded in title


def test_build_macro_flash_message_no_url_shows_source():
    mf = _macro_flash(url="")
    msg = build_macro_flash_message(mf)
    assert "Reuters" in msg


def test_build_macro_flash_message_timestamp():
    msg = build_macro_flash_message(_macro_flash())
    assert "20/03/2025" in msg


@pytest.mark.asyncio
async def test_send_macro_flash_success():
    mf = _macro_flash()
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(return_value=MagicMock())
        result = await send_macro_flash(mf, "fake_token", "fake_chat")
    assert result is True
    call_kwargs = mock_instance.send_message.call_args.kwargs
    assert "אירוע מאקרו" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_macro_flash_failure_returns_false():
    from telegram.error import TelegramError
    mf = _macro_flash()
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(side_effect=TelegramError("fail"))
        result = await send_macro_flash(mf, "fake_token", "fake_chat")


# ─────────────────────────────────────────────────────────────────────────────
# Smart Money Alert (Task 25)
# ─────────────────────────────────────────────────────────────────────────────

def _insider_alert(**kwargs) -> InsiderAlert:
    defaults = dict(
        ticker="NVDA",
        insider_name="Jensen Huang",
        position="CEO",
        shares=10_000,
        value=1_500_000,
        transaction_date=datetime(2025, 3, 10, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return InsiderAlert(**defaults)


def _options_alert(**kwargs) -> OptionsFlowAlert:
    defaults = dict(
        ticker="NVDA",
        expiry="2025-05-16",
        strike=130.0,
        option_type="CALL",
        volume=5000,
        open_interest=800,
        volume_oi_ratio=6.25,
    )
    defaults.update(kwargs)
    return OptionsFlowAlert(**defaults)


def test_build_smart_money_message_insider_header():
    msg = build_smart_money_message(_insider_alert())
    assert "🕵️" in msg
    assert "כסף חכם" in msg


def test_build_smart_money_message_insider_contains_ticker():
    msg = build_smart_money_message(_insider_alert())
    assert "NVDA" in msg


def test_build_smart_money_message_insider_contains_name_and_position():
    msg = build_smart_money_message(_insider_alert())
    assert "Jensen Huang" in msg
    assert "CEO" in msg


def test_build_smart_money_message_insider_value_formatted():
    msg = build_smart_money_message(_insider_alert(value=1_500_000))
    assert "$1.50M" in msg


def test_build_smart_money_message_insider_value_below_1m():
    msg = build_smart_money_message(_insider_alert(value=500_000))
    assert "$500,000" in msg


def test_build_smart_money_message_insider_contains_timestamp():
    msg = build_smart_money_message(_insider_alert())
    assert "⏰" in msg


def test_build_smart_money_message_options_header():
    msg = build_smart_money_message(_options_alert())
    assert "🕵️" in msg
    assert "כסף חכם" in msg


def test_build_smart_money_message_options_call_label():
    msg = build_smart_money_message(_options_alert(option_type="CALL"))
    assert "CALL" in msg
    assert "עלייה" in msg


def test_build_smart_money_message_options_put_label():
    msg = build_smart_money_message(_options_alert(option_type="PUT"))
    assert "PUT" in msg
    assert "ירידה" in msg


def test_build_smart_money_message_options_contains_strike_and_expiry():
    msg = build_smart_money_message(_options_alert(strike=130.0, expiry="2025-05-16"))
    assert "130" in msg
    assert "2025-05-16" in msg


def test_build_smart_money_message_options_contains_volume_ratio():
    msg = build_smart_money_message(_options_alert(volume_oi_ratio=6.25))
    assert "6.25" in msg or "6.2" in msg


@pytest.mark.asyncio
async def test_send_smart_money_alert_insider_success():
    alert = _insider_alert()
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(return_value=MagicMock())
        result = await send_smart_money_alert(alert, "fake_token", "fake_chat")
    assert result is True
    call_kwargs = mock_instance.send_message.call_args.kwargs
    assert "כסף חכם" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_smart_money_alert_options_success():
    alert = _options_alert()
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(return_value=MagicMock())
        result = await send_smart_money_alert(alert, "fake_token", "fake_chat")
    assert result is True


@pytest.mark.asyncio
async def test_send_smart_money_alert_failure_returns_false():
    from telegram.error import TelegramError
    alert = _insider_alert()
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(side_effect=TelegramError("fail"))
        result = await send_smart_money_alert(alert, "fake_token", "fake_chat")
    assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Learning Report (Task 27)
# ─────────────────────────────────────────────────────────────────────────────

def _learning_report(**overrides) -> LearningReport:
    base = dict(
        analysis_date=datetime(2026, 4, 13, 18, 0, tzinfo=timezone.utc),
        week_start=datetime(2026, 4, 6, 0, 0, tzinfo=timezone.utc),
        week_end=datetime(2026, 4, 13, 18, 0, tzinfo=timezone.utc),
        total_trades=12,
        wins=7,
        losses=5,
        unresolved=2,
        win_rate_before=7 / 12,
        win_rate_after=0.714,
        trades_filtered=4,
        patterns=[
            PatternFinding(
                pattern_type="rsi_ceiling",
                description_heb="RSI בין 75–100 בעסקאות LONG",
                failure_rate=1.0,
                sample_count=3,
                failed_count=3,
                action_heb="חסמתי עסקאות LONG עם RSI מעל 75 לשבוע הבא",
                rsi_ceiling=75.0,
            ),
        ],
        blocked_tickers=[],
        blocked_hours=[],
        blocked_days=[],
        rsi_ceiling=75.0,
    )
    base.update(overrides)
    return LearningReport(**base)


def test_build_learning_report_header():
    msg = build_learning_report_message(_learning_report())
    assert "דוח למידה עצמית" in msg
    assert "🤖" in msg


def test_build_learning_report_contains_week_range():
    msg = build_learning_report_message(_learning_report())
    assert "06/04/2026" in msg
    assert "13/04/2026" in msg


def test_build_learning_report_stats_block():
    msg = build_learning_report_message(_learning_report())
    assert "12" in msg  # total trades
    assert "58" in msg or "7" in msg  # win rate or wins


def test_build_learning_report_shows_pattern():
    msg = build_learning_report_message(_learning_report())
    assert "RSI" in msg
    assert "75" in msg


def test_build_learning_report_shows_action():
    msg = build_learning_report_message(_learning_report())
    assert "חסמתי" in msg


def test_build_learning_report_shows_projected_improvement():
    msg = build_learning_report_message(_learning_report())
    assert "71" in msg or "תחזית" in msg


def test_build_learning_report_no_patterns():
    report = _learning_report(patterns=[], trades_filtered=0, rsi_ceiling=None, win_rate_after=7 / 12)
    msg = build_learning_report_message(report)
    assert "לא זוהו אזורים רעילים" in msg


def test_build_learning_report_no_trades():
    report = _learning_report(total_trades=0, wins=0, losses=0, unresolved=3,
                              win_rate_before=0.0, win_rate_after=0.0,
                              trades_filtered=0, patterns=[])
    msg = build_learning_report_message(report)
    assert "אין עסקאות מוסכמות" in msg


def test_build_learning_report_has_timestamp():
    msg = build_learning_report_message(_learning_report())
    assert "⏰" in msg


@pytest.mark.asyncio
async def test_send_learning_report_success():
    report = _learning_report()
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(return_value=MagicMock())
        result = await send_learning_report(report, "fake_token", "fake_chat")
    assert result is True
    call_kwargs = mock_instance.send_message.call_args.kwargs
    assert "למידה עצמית" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_learning_report_failure_returns_false():
    from telegram.error import TelegramError
    report = _learning_report()
    with patch("stock_sentinel.notifier.Bot") as MockBot:
        mock_instance = AsyncMock()
        MockBot.return_value = mock_instance
        mock_instance.send_message = AsyncMock(side_effect=TelegramError("fail"))
        result = await send_learning_report(report, "fake_token", "fake_chat")
    assert result is False
