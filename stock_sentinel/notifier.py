import logging
import asyncio
from datetime import datetime, timezone
from telegram import Bot
from telegram.error import TelegramError
from stock_sentinel.models import Alert
from stock_sentinel.translator import translate_to_hebrew
from stock_sentinel.visualizer import generate_chart  # re-export for backward compat

log = logging.getLogger(__name__)

# ── re-export so scheduler.py import stays unchanged ─────────────────────────
__all__ = ["build_message", "generate_chart", "send_alert",
           "build_daily_report", "send_daily_report", "send_trade_update"]


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pct(price: float, entry: float) -> float:
    """Percentage change from entry to price."""
    if not entry:
        return 0.0
    return (price - entry) / entry * 100.0


def _score_label(score: float) -> str:
    if score >= 8.0:
        return "סנטימנט מוסדי חזק"
    if score >= 6.0:
        return "סנטימנט מוסדי בינוני"
    if score >= 4.0:
        return "סנטימנט ניטרלי"
    return "סנטימנט מוסדי חלש"


def _horizon_label(horizon: str) -> str:
    return {
        "SHORT_TERM": "טווח קצר (סווינג — 2 עד 10 ימי מסחר)",
        "LONG_TERM":  "טווח ארוך (פוזיציה — 3 עד 8 שבועות)",
        "BOTH":       "קצר וארוך (2–10 ימים ועד 8 שבועות)",
    }.get(horizon, "")


def _build_analyst_summary(alert: Alert) -> str:
    """Compose a multi-sentence professional Hebrew analyst summary."""
    parts: list[str] = []

    # VWAP support / resistance
    if alert.vwap and alert.entry:
        if alert.direction == "LONG" and alert.vwap <= alert.entry * 1.02:
            parts.append(
                f"המניה נתמכת על ה-VWAP (${alert.vwap:.2f}) — סימן לעניין מוסדי קנייתי"
            )
        elif alert.direction == "SHORT" and alert.vwap >= alert.entry * 0.98:
            parts.append(
                f"המניה נתקלת בהתנגדות VWAP (${alert.vwap:.2f}) — לחץ מכירה מוסדי"
            )

    # POC proximity
    if alert.poc_price and alert.entry:
        if abs(alert.poc_price - alert.entry) / alert.entry < 0.04:
            parts.append(
                f"ה-POC (${alert.poc_price:.2f}) סמוך לאזור הכניסה — ריכוז נפח מסחר משמעותי"
            )

    # Fibonacci Golden Pocket
    if alert.fib_618 and alert.entry:
        if abs(alert.fib_618 - alert.entry) / alert.entry < 0.05:
            parts.append(
                f"רמת פיבונאצ'י 0.618 (${alert.fib_618:.2f}) מספקת תמיכה/התנגדות קריטית"
            )

    # Golden Cross
    if alert.golden_cross:
        parts.append(
            "ממוצע 50 חצה מעל ממוצע 200 (Golden Cross) — אישור מגמה עולה לטווח ארוך"
        )

    # RSI Divergence
    if alert.rsi_divergence == "bullish":
        parts.append(
            "דיברגנס שורי ב-RSI מצביע על היחלשות לחץ המוכרים — היפוך כלפי מעלה צפוי"
        )
    elif alert.rsi_divergence == "bearish":
        parts.append(
            "דיברגנס דובי ב-RSI מצביע על היחלשות המומנטום — היפוך כלפי מטה צפוי"
        )

    # Volume + pattern combo
    if alert.confluence_factors:
        has_vol = any("Volume" in f for f in alert.confluence_factors)
        has_pat = any(
            kw in f for f in alert.confluence_factors
            for kw in ("Pattern", "Engulfing", "Hammer", "Shooting")
        )
        if has_vol and has_pat:
            parts.append(
                "שילוב פריצת ווליום עם תבנית נרות מחזק את אמינות האיתות"
            )

    if not parts:
        return alert.horizon_reason or "האיתות מבוסס על מספר גורמי התכנסות טכניים."

    return ". ".join(parts) + "."


# ─────────────────────────────────────────────────────────────────────────────
# Public: build_message
# ─────────────────────────────────────────────────────────────────────────────

def build_message(alert: Alert, headlines: list[str]) -> str:
    """Build the Expert-Tier Hebrew Telegram alert message (RTL-optimised)."""
    direction_emoji = "📈" if alert.direction == "LONG" else "📉"
    direction_heb   = "קניה (LONG)" if alert.direction == "LONG" else "מכירה (SHORT)"

    # Resolve percentages — prefer pre-computed, fall back to inline calc
    pct_sl  = alert.pct_sl  if alert.pct_sl  else _pct(alert.stop_loss,     alert.entry)
    pct_tp1 = alert.pct_tp1 if alert.pct_tp1 else _pct(alert.take_profit_1 or alert.take_profit, alert.entry)
    pct_tp2 = alert.pct_tp2 if alert.pct_tp2 else _pct(alert.take_profit,   alert.entry)
    pct_tp3 = alert.pct_tp3 if alert.pct_tp3 else _pct(alert.take_profit_3 or alert.take_profit, alert.entry)

    tp1_price = alert.take_profit_1 if alert.take_profit_1 else alert.take_profit
    tp3_price = alert.take_profit_3 if alert.take_profit_3 else alert.take_profit

    lines = [
        f"🎯 *איתות למסחר — {alert.ticker}*",
        f"{direction_emoji} כיוון: *{direction_heb}*",
    ]

    horizon_lbl = _horizon_label(alert.horizon)
    if horizon_lbl:
        lines.append(f"⏳ אופק טרייד: {horizon_lbl}")

    if alert.institutional_score:
        s_lbl = _score_label(alert.institutional_score)
        lines.append(f"📊 ציון איכות כולל: `{alert.institutional_score:.1f}/10` ({s_lbl})")

    lines += [
        "",
        "💰 *יעדים ורווח פוטנציאלי:*",
        f"  • כניסה:          `${alert.entry:.2f}`",
        f"  • 🛡 סטופ לוס:    `${alert.stop_loss:.2f}` (`{pct_sl:+.1f}%`)",
        f"  • 🎯 יעד 1:       `${tp1_price:.2f}` (`{pct_tp1:+.1f}%`)",
        f"  • 🚀 יעד 2:       `${alert.take_profit:.2f}` (`{pct_tp2:+.1f}%`)",
        f"  • 🏆 יעד 3:       `${tp3_price:.2f}` (`{pct_tp3:+.1f}%`)",
    ]

    # ── Technical metrics row ────────────────────────────────────────────────
    tech_parts = [f"RSI: `{alert.rsi:.1f}`"]
    if alert.vwap:
        tech_parts.append(f"VWAP: `${alert.vwap:.2f}`")
    if alert.poc_price:
        tech_parts.append(f"POC: `${alert.poc_price:.2f}`")
    lines += ["", "🔬 *מדדים טכניים:*", "  " + "  |  ".join(tech_parts)]

    # Pivot levels
    if alert.pivot_r1 and alert.pivot_s1:
        lines.append(
            f"  התנגדות: R1 `${alert.pivot_r1:.2f}` / R2 `${alert.pivot_r2:.2f}`"
        )
        lines.append(
            f"  תמיכה:   S1 `${alert.pivot_s1:.2f}` / S2 `${alert.pivot_s2:.2f}`"
        )

    # RSI divergence
    if alert.rsi_divergence == "bullish":
        lines.append("  ↗ דיברגנס שורי ב-RSI מזוהה")
    elif alert.rsi_divergence == "bearish":
        lines.append("  ↘ דיברגנס דובי ב-RSI מזוהה")

    # Headlines
    if headlines:
        lines += ["", "📢 *חדשות מאומתות:*"]
        for h in headlines[:5]:
            lines.append(f"  • {translate_to_hebrew(h)}")

    # Confluence factors
    if alert.confluence_factors:
        lines += ["", "🎯 *גורמי התכנסות הטרייד:*"]
        for f in alert.confluence_factors:
            lines.append(f"  ✅ {translate_to_hebrew(f)}")

    # Analyst summary
    summary = _build_analyst_summary(alert)
    if summary:
        lines += ["", "💡 *ניתוח אנליסט (אסטרטגיה):*", f"  {summary}"]

    lines += [
        "",
        f"⏰ _{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC_",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Telegram dispatch
# ─────────────────────────────────────────────────────────────────────────────

async def send_alert(
    alert: Alert, headlines: list[str], bot_token: str, chat_id: str
) -> int | None:
    """Send alert via Telegram with 3 retries. Returns message_id on success, None on failure."""
    import os
    bot  = Bot(token=bot_token)
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


# ─────────────────────────────────────────────────────────────────────────────
# Daily report
# ─────────────────────────────────────────────────────────────────────────────

def build_daily_report(stats: dict) -> str:
    """Build Hebrew daily performance summary message."""
    total     = stats.get("total", 0)
    wins      = stats.get("wins", 0)
    losses    = stats.get("losses", 0)
    win_rate  = stats.get("win_rate", 0.0)
    top_facs  = stats.get("top_factors", [])

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

    if top_facs:
        lines += ["", "🏆 *גורמי מכנס מובילים (WIN):*"]
        for i, factor in enumerate(top_facs, 1):
            lines.append(f"  {i}. {translate_to_hebrew(factor)}")

    lines += [
        "",
        f"⏰ _{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC_",
    ]
    return "\n".join(lines)


async def send_daily_report(stats: dict, bot_token: str, chat_id: str) -> bool:
    """Send daily performance report via Telegram. Returns True on success."""
    bot  = Bot(token=bot_token)
    text = build_daily_report(stats)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        return True
    except TelegramError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Trade update (threaded reply)
# ─────────────────────────────────────────────────────────────────────────────

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
    ticker     = trade.get("ticker", "?")
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
