import logging
import os
import tempfile
import asyncio
import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf
import pandas as pd
from datetime import datetime, timezone
from telegram import Bot
from telegram.error import TelegramError
from stock_sentinel.models import Alert, TechnicalSignal
from stock_sentinel.translator import translate_to_hebrew

log = logging.getLogger(__name__)


def build_message(alert: Alert, headlines: list[str]) -> str:
    """Build Hebrew professional Telegram alert — RTL optimised."""
    direction_emoji = "📈" if alert.direction == "LONG" else "📉"
    direction_heb = "קניה (LONG)" if alert.direction == "LONG" else "מכירה (SHORT)"

    # --- Horizon label ---
    horizon_map = {
        "SHORT_TERM": "📅 טווח קצר (2-14 יום)",
        "LONG_TERM":  "📆 לטווח ארוך (שבועות/חודשים)",
        "BOTH":       "📅📆 קצר וארוך כאחד",
    }
    horizon_line = horizon_map.get(alert.horizon, "")

    lines = [
        f"🎯 *איתות למסחר — {alert.ticker}*",
        f"{direction_emoji} כיוון: *{direction_heb}*",
    ]
    if horizon_line:
        lines.append(f"⏳ תקופת זמן לטרייד: {horizon_line}")

    lines += [
        "",
        "💰 *נתונים טכניים*",
        f"  נקודת כניסה:        `${alert.entry:.2f}`",
        f"  🛡 סטופ לוס:         `${alert.stop_loss:.2f}`",
        f"  🎯 יעד 1 (שמרני):   `${alert.take_profit_1:.2f}`",
        f"  🎯 יעד 2 (מתון):    `${alert.take_profit:.2f}`",
        f"  🏆 יעד 3 (שאפתני): `${alert.take_profit_3:.2f}`",
        f"  RSI:                 `{alert.rsi:.1f}`",
        "",
        "🧠 *תחושת שוק* (RSS 40% | חדשות 40% | סושיאל 20%)",
        f"  ציון משולב: `{alert.sentiment_score:+.2f}`",
        f"  RSS:        `{alert.rss_score:+.2f}`",
        f"  חדשות:      `{alert.news_score:+.2f}`",
        f"  סושיאל:     `{alert.twitter_score:+.2f}`",
    ]

    if headlines:
        lines += ["", "📢 *חדשות מאומתות*"]
        for h in headlines[:5]:
            translated = translate_to_hebrew(h)
            lines.append(f"  • {translated}")

    if alert.confluence_factors:
        lines += ["", "🎯 *גורמי התכנסות הטרייד*"]
        for f in alert.confluence_factors:
            translated = translate_to_hebrew(f)
            lines.append(f"  ✅ {translated}")

    if alert.horizon_reason:
        lines += ["", "💡 *הסבר האסטרטגיה*", f"  {alert.horizon_reason}"]

    lines += [
        "",
        f"⏰ _{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC_",
    ]
    return "\n".join(lines)


def generate_chart(ticker: str, df: pd.DataFrame, signal: TechnicalSignal) -> str:
    """Generate candlestick chart with SMA20/SMA50 overlays. Returns temp file path."""
    df_full = df.copy()
    ma20_full = df_full["Close"].rolling(20).mean()
    ma50_full = df_full["Close"].rolling(50).mean()
    plot_df = df_full.tail(30)
    ma20 = ma20_full.iloc[-30:]
    ma50 = ma50_full.iloc[-30:]
    adds = [
        mpf.make_addplot(ma20, color="blue", width=1.2, label="SMA20"),
        mpf.make_addplot(ma50, color="orange", width=1.2, label="SMA50"),
    ]
    path = os.path.join(
        tempfile.gettempdir(),
        f"stock_sentinel_{ticker}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.png",
    )
    mpf.plot(
        plot_df,
        type="candle",
        style="charles",
        addplot=adds,
        title=f"{ticker} | RSI: {signal.rsi:.1f} | {signal.direction}",
        savefig=dict(fname=path, dpi=150, bbox_inches="tight"),
        figsize=(10, 6),
    )
    return path


async def send_alert(
    alert: Alert, headlines: list[str], bot_token: str, chat_id: str
) -> int | None:
    """Send alert via Telegram with 3 retries. Returns message_id on success, None on failure."""
    bot = Bot(token=bot_token)
    text = build_message(alert, headlines)
    for attempt in range(3):
        try:
            if alert.chart_path and os.path.exists(alert.chart_path):
                with open(alert.chart_path, "rb") as photo:
                    msg = await bot.send_photo(
                        chat_id=chat_id, photo=photo, caption=text, parse_mode="Markdown"
                    )
            else:
                msg = await bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="Markdown"
                )
            return msg.message_id
        except TelegramError:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt * 2)
    return None


def build_daily_report(stats: dict) -> str:
    """Build Hebrew daily performance summary message."""
    total = stats.get("total", 0)
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    win_rate = stats.get("win_rate", 0.0)
    top_factors = stats.get("top_factors", [])

    if total == 0:
        return "📊 *דוח יומי — Stock Sentinel*\n\nלא נשלחו התראות היום."

    lines = [
        "📊 *דו\"ח ביצועים יומי — Stock Sentinel*",
        "",
        f"  סה\"כ עסקאות: `{total}`",
        f"  ✅ הצלחות:   `{wins}`",
        f"  ❌ כישלונות: `{losses}`",
        f"  🎯 אחוז הצלחה: `{win_rate:.0%}`",
    ]

    if top_factors:
        lines += ["", "🏆 *גורמי מכנס מובילים (WIN)*"]
        for i, factor in enumerate(top_factors, 1):
            translated = translate_to_hebrew(factor)
            lines.append(f"  {i}. {translated}")

    lines += [
        "",
        f"⏰ _{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC_",
    ]
    return "\n".join(lines)


async def send_daily_report(stats: dict, bot_token: str, chat_id: str) -> bool:
    """Send daily performance report via Telegram. Returns True on success."""
    bot = Bot(token=bot_token)
    text = build_daily_report(stats)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        return True
    except TelegramError:
        return False


async def send_trade_update(
    trade: dict,
    update_type: str,
    current_price: float,
    bot_token: str,
    chat_id: str,
) -> bool:
    """Send a threaded trade update reply to the original alert message.

    update_type: 'TP1', 'TP2', 'TP3', or 'SL'.
    Uses reply_to_message_id so it threads under the original alert.
    Returns True on success.
    """
    ticker = trade.get("ticker", "?")
    message_id = trade.get("telegram_message_id")

    if update_type == "SL":
        text = (
            f"🔔 *עדכון טרייד: {ticker}*\n\n"
            f"🛑 *סטופ לוס הופעל. סגירת פוזיציה.*\n"
            f"  מחיר נוכחי: `${current_price:.2f}`\n\n"
            f"📊 *סטטוס:* הטרייד נסגר."
        )
    elif update_type in ("TP1", "TP2", "TP3"):
        _tp_info = {
            "TP1": ("1", "שמרני",  "הטרייד ממשיך ליעד הבא 🎯"),
            "TP2": ("2", "מתון",   "הטרייד ממשיך ליעד הבא 🎯"),
            "TP3": ("3", "שאפתני", "נסגר ברווח מקסימלי 🏆"),
        }
        tp_num, tp_label, status = _tp_info[update_type]
        text = (
            f"🔔 *עדכון טרייד: {ticker}*\n\n"
            f"✅ *יעד {tp_num} ({tp_label}) הושג!*\n"
            f"  מחיר: `${current_price:.2f}`\n\n"
            f"📊 *סטטוס:* {status}"
        )
    else:
        return False

    bot = Bot(token=bot_token)
    try:
        kwargs: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if message_id:
            kwargs["reply_to_message_id"] = int(message_id)
        await bot.send_message(**kwargs)
        return True
    except TelegramError as exc:
        log.warning("send_trade_update failed for %s %s: %s", ticker, update_type, exc)
        return False
