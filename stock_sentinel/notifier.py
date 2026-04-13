import logging
import asyncio
import os
from datetime import datetime, timezone
from telegram import Bot
from telegram.error import TelegramError
from stock_sentinel.models import Alert, DebateResult, InsiderAlert, LearningReport, MacroFlash, NewsFlash, OptionsFlowAlert
from stock_sentinel.translator import translate_to_hebrew
from stock_sentinel.visualizer import generate_chart  # re-export for backward compat

log = logging.getLogger(__name__)


# ── Israel Time helper ────────────────────────────────────────────────────────

def _now_israel() -> datetime:
    """Return current datetime in Israel Time (handles DST automatically)."""
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        return datetime.now(ZoneInfo("Asia/Jerusalem"))
    except Exception:
        from datetime import timedelta
        # Fallback: IDT = UTC+3 (summer), IST = UTC+2 (winter).
        # April through October is summer in Israel.
        now_utc = datetime.now(timezone.utc)
        offset  = timedelta(hours=3 if 4 <= now_utc.month <= 10 else 2)
        return now_utc.astimezone(timezone(offset))


def _israel_ts(dt: datetime | None = None) -> str:
    """Formatted Israel timestamp: DD/MM/YYYY HH:MM."""
    if dt is None:
        t = _now_israel()
    else:
        try:
            from zoneinfo import ZoneInfo
            t = dt.astimezone(ZoneInfo("Asia/Jerusalem"))
        except Exception:
            from datetime import timedelta
            now_utc = dt.astimezone(timezone.utc)
            offset  = timedelta(hours=3 if 4 <= now_utc.month <= 10 else 2)
            t = now_utc.astimezone(timezone(offset))
    return t.strftime("%d/%m/%Y %H:%M")

# ── re-export so scheduler.py import stays unchanged ─────────────────────────
__all__ = ["build_message", "generate_chart", "send_alert",
           "build_daily_report", "send_daily_report", "send_trade_update",
           "build_news_flash_message", "send_news_flash",
           "build_macro_flash_message", "send_macro_flash",
           "build_smart_money_message", "send_smart_money_alert",
           "build_debate_section",
           "build_learning_report_message", "send_learning_report",
           # Scheduled reports
           "send_morning_brief", "send_premarket_catalysts",
           "build_daily_performance_report", "send_daily_performance_report"]


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

def _build_ma_ribbon_summary(alert: Alert) -> str:
    """Compose a detailed Hebrew analyst paragraph covering MA Ribbon, Fibonacci, and Volume Profile."""
    parts: list[str] = []

    # ── MA Ribbon ────────────────────────────────────────────────────────────
    if alert.golden_cross:
        parts.append(
            "ממוצע 50 חצה מעל ממוצע 200 (Golden Cross) — ה-MA Ribbon מאשר מגמה עולה ארוכת טווח"
        )
    elif alert.ema_21 and alert.entry:
        rel = "מעל" if alert.entry > alert.ema_21 else "מתחת ל"
        parts.append(
            f"המחיר נמצא {rel} EMA 21 (${alert.ema_21:.2f})"
            + (" — סימן לאיבוד המומנטום הקצר" if alert.entry < alert.ema_21 else " — מומנטום קצר-טווח בריא")
        )

    # ── Fibonacci Golden Pocket ───────────────────────────────────────────────
    if alert.fib_618 and alert.entry:
        dist_pct = abs(alert.fib_618 - alert.entry) / alert.entry * 100
        if dist_pct < 5.0:
            role = "תמיכה" if alert.direction == "LONG" else "התנגדות"
            parts.append(
                f"רמת פיבונאצ'י 0.618 (${alert.fib_618:.2f}) מספקת {role} — הכיס הזהב מאמת את נקודת הכניסה"
            )

    # ── Volume Profile / POC ──────────────────────────────────────────────────
    if alert.poc_price and alert.entry:
        dist_pct = abs(alert.poc_price - alert.entry) / alert.entry * 100
        if dist_pct < 4.0:
            parts.append(
                f"ה-POC (${alert.poc_price:.2f}) צמוד לכניסה — ריכוז נפח מסחר מוסדי משמעותי באזור זה"
            )

    # ── VWAP ─────────────────────────────────────────────────────────────────
    if alert.vwap and alert.entry:
        if alert.direction == "LONG" and alert.vwap <= alert.entry * 1.02:
            parts.append(f"VWAP (${alert.vwap:.2f}) תומך במחיר מלמטה — זרם מוסדי קנייתי")
        elif alert.direction == "SHORT" and alert.vwap >= alert.entry * 0.98:
            parts.append(f"VWAP (${alert.vwap:.2f}) מהווה התנגדות — לחץ מוסדי כלפי מטה")

    # ── RSI Divergence ────────────────────────────────────────────────────────
    if alert.rsi_divergence == "bullish":
        parts.append("דיברגנס שורי ב-RSI מאשר היחלשות המוכרים — מומנטום הפוך צפוי")
    elif alert.rsi_divergence == "bearish":
        parts.append("דיברגנס דובי ב-RSI מאשר היחלשות הקונים — מומנטום הפוך כלפי מטה")

    # ── Risk/Reward ───────────────────────────────────────────────────────────
    if alert.risk_reward and alert.risk_reward >= 1.5:
        parts.append(f"יחס סיכון/תגמול: {alert.risk_reward:.1f} — עסקה כדאית לביצוע")

    if not parts:
        return alert.horizon_reason or "האיתות מבוסס על מספר גורמי התכנסות טכניים."

    return ". ".join(parts) + "."


def _build_trade_rationale(alert: Alert) -> str:
    """1-2 sentence Hebrew trade rationale — the 'why now, why this direction'."""
    direction_heb = "קנייה" if alert.direction == "LONG" else "מכירה בחסר"
    horizon_map   = {
        "SHORT_TERM": "סווינג קצר טווח",
        "LONG_TERM":  "פוזיציה ארוכת טווח",
        "BOTH":       "סווינג וגם פוזיציה",
    }
    horizon_heb = horizon_map.get(alert.horizon, "")

    # Distil the strongest confluence signal into one sentence
    factors = alert.confluence_factors or []
    if alert.golden_cross:
        tech_note = "חצייה Golden Cross מאשרת מגמת עלייה מוסדית"
    elif alert.rsi_divergence == "bullish":
        tech_note = "דיברגנס שורי ב-RSI מאשר היחלשות המוכרים"
    elif alert.rsi_divergence == "bearish":
        tech_note = "דיברגנס דובי ב-RSI מאשר היחלשות הקונים"
    elif any("BOS" in f or "Break of Structure" in f for f in factors):
        tech_note = "שבירת מבנה (BOS) מאשרת כיוון מוסדי"
    elif any("VWAP" in f for f in factors):
        tech_note = "מחיר מעל ה-VWAP — זרם קניות מוסדי"
    elif any("Volume Spike" in f or "Volume" in f for f in factors):
        tech_note = "פריצת ווליום חריגה מאשרת עניין מוסדי"
    else:
        tech_note = "מספר גורמי התכנסות טכניים תואמים"

    rr_note = (f" | יחס סיכון/תגמול {alert.risk_reward:.1f}" if alert.risk_reward >= 1.5 else "")
    horizon_note = f" — {horizon_heb}" if horizon_heb else ""

    return (
        f"עסקת {direction_heb}{horizon_note}: {tech_note}{rr_note}. "
        f"הכניסה מומלצת סמוך ל-${alert.entry:.2f} עם ניהול סיכון קפדני."
    )


def _confidence_bar(score: int) -> str:
    """Visual confidence bar: 10 blocks, filled proportionally."""
    filled = round(score / 10)
    bar    = "█" * filled + "░" * (10 - filled)
    if score >= 75:
        emoji = "🟢"
    elif score >= 50:
        emoji = "🟡"
    else:
        emoji = "🔴"
    return f"{emoji} [{bar}] {score}%"


def build_debate_section(debate: DebateResult) -> list[str]:
    """Return formatted lines for 👁️ Visual Analysis and 🧠 Agent Council sections."""
    lines: list[str] = []

    # ── Visionary section (only when a pattern was identified) ────────────────
    if debate.visionary_pattern:
        confirms_emoji = "✅" if debate.visionary_confirms else "⚠️"
        confirms_text  = "מאשר את הסיגנל" if debate.visionary_confirms else "סותר את הסיגנל"
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "👁️ *ניתוח ויזואלי (Computer Vision)*",
            "",
            f"🔍 *תבנית שזוהתה:* {debate.visionary_pattern}",
            f"{confirms_emoji} *סטטוס:* {confirms_text}",
        ]

    # ── Agent Council section ─────────────────────────────────────────────────
    rec_map = {
        "כנס":                    "✅ המלצה: כנס לפוזיציה",
        "הימנע":                  "❌ המלצה: הימנע מהעסקה",
        "המתן לאישור נוסף":       "⏳ המלצה: המתן לאישור נוסף",
    }

    # Extract recommendation from full judge text if possible
    recommendation = ""
    try:
        from stock_sentinel.debate_engine import _extract_json
        judge_data = _extract_json(debate.full_judge)
        rec_raw    = judge_data.get("המלצה", "")
        recommendation = rec_map.get(rec_raw, f"✅ {rec_raw}" if rec_raw else "")
        reasoning  = judge_data.get("נימוק", "")
        verdict    = debate.judge_verdict
    except Exception:
        reasoning  = ""
        verdict    = debate.judge_verdict

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🧠 *סיכום מועצת הסוכנים*",
        "",
        f"🐂 *השור:* {debate.bull_argument}",
        "",
        f"🐻 *הדוב:* {debate.bear_argument}",
        "",
        "⚖️ *פסיקת השופט:*",
        f"  {verdict}",
    ]

    if reasoning and reasoning != verdict:
        lines.append(f"  _{reasoning}_")

    lines += [
        "",
        f"🎯 *רמת ביטחון:* {_confidence_bar(debate.confidence_score)}",
    ]

    if recommendation:
        lines += ["", f"*{recommendation}*"]

    return lines


def build_message(alert: Alert, headlines: list[str], debate: DebateResult | None = None) -> str:
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

    # ── Header: scanner hit vs watchlist ─────────────────────────────────────
    if getattr(alert, "scanner_hit", False):
        header = f"🔍 *מנייה חמה התגלתה בסריקה — {alert.ticker}*"
    else:
        header = f"🎯 *איתות למסחר — {alert.ticker}*"

    lines = [
        header,
        f"{direction_emoji} כיוון: *{direction_heb}*",
    ]

    horizon_lbl = _horizon_label(alert.horizon)
    if horizon_lbl:
        lines.append(f"⏳ אופק טרייד: {horizon_lbl}")

    if alert.institutional_score:
        s_lbl = _score_label(alert.institutional_score)
        lines.append(f"📊 ציון איכות כולל: `{alert.institutional_score:.1f}/10` ({s_lbl})")

    rr_str = f"  | יחס ס/ת: `{alert.risk_reward:.1f}`" if alert.risk_reward else ""
    lines += [
        "",
        "💰 *יעדים ורווח פוטנציאלי:*",
        f"  • כניסה:          `${alert.entry:.2f}`{rr_str}",
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

    # Analyst summary (MA Ribbon + Fibonacci + Volume Profile)
    summary = _build_ma_ribbon_summary(alert)
    if summary:
        lines += ["", "💡 *סיכום אנליסט:*", f"  {summary}"]

    # Trade rationale — the 'why this trade, why now'
    rationale = _build_trade_rationale(alert)
    lines += ["", "🔑 *רציונל העסקה:*", f"  {rationale}"]

    # Agent Council debate section (optional)
    if debate is not None:
        lines += build_debate_section(debate)

    lines += [
        "",
        f"⏰ _{_israel_ts()}_",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# News Flash (Task 19)
# ─────────────────────────────────────────────────────────────────────────────

def build_news_flash_message(flash: NewsFlash) -> str:
    """Build Hebrew Telegram message for a breaking news flash.

    Structure:
      [Header]
      💡 כותרת  — the translated headline
      ━━━
      📊 ניתוח  — AI-generated bullet-point analysis (the 'why', not the 'what')
      ⏰ timestamp | 🟢/🔴 bottom-line sentiment verdict
    """
    is_watchlist = getattr(flash, "is_watchlist", True)
    header = (
        f"📢 *מבזק חדשות — {flash.ticker}*"
        if is_watchlist
        else f"💎 *גילוי הזדמנות — {flash.ticker}*"
    )

    source_suffix = f"  _{flash.source}_" if flash.source else ""

    # ── Summary / analysis section ────────────────────────────────────────────
    # The AI writes in Hebrew with bullet points (•) when relevant.
    # We display it under an "ניתוח" label so it's clearly distinct from the
    # raw translated headline above.
    summary_lines: list[str] = []
    for line in flash.summary.splitlines():
        stripped = line.strip()
        if stripped:
            summary_lines.append(f"  {stripped}")

    # ── Sentiment bottom line ─────────────────────────────────────────────────
    is_bullish = flash.reaction == "bullish" or flash.sentiment_score > 0
    is_bearish = flash.reaction == "bearish" or flash.sentiment_score < 0
    if is_bullish:
        sentiment_line = "🟢 *מסקנה: סנטימנט שורי — לחץ קנייה אפשרי*"
    elif is_bearish:
        sentiment_line = "🔴 *מסקנה: סנטימנט דובי — לחץ מכירה אפשרי*"
    else:
        sentiment_line = "⚪ *מסקנה: סנטימנט ניטרלי*"

    lines = [
        header,
        "",
        f"💡 *כותרת:* {flash.title}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "📊 *ניתוח:*",
        *summary_lines,
        "",
        f"⏰ _{_israel_ts(flash.published_at)}_{source_suffix}",
        "",
        sentiment_line,
    ]

    return "\n".join(lines)


async def send_news_flash(flash: NewsFlash, bot_token: str, chat_id: str) -> bool:
    """Send a breaking news flash via Telegram. Returns True on success."""
    bot  = Bot(token=bot_token)
    text = build_news_flash_message(flash)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        return True
    except TelegramError as exc:
        log.warning("send_news_flash failed for %s: %s", flash.ticker, exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Macro Flash (Task 23)
# ─────────────────────────────────────────────────────────────────────────────

def _build_macro_bottom_line(flash: MacroFlash) -> str:
    """Generate a Hebrew 'bottom line' sentence from macro reaction and assets."""
    assets = " ,".join(flash.affected_assets[:3]) if flash.affected_assets else "השוק"
    influencers = flash.influencers or []

    if flash.reaction == "bullish":
        if any(k in influencers for k in ("Fed", "FOMC", "Interest Rates", "Interest Rate")):
            return f"בשורה התחתונה: ציפיות להקלה מוניטרית — זרימת כסף צפויה לכיוון {assets}."
        return f"בשורה התחתונה: אירוע חיובי לשוק — תנודתיות עולה ב-{assets}, הטיה לכיוון עלייה."
    else:
        if any(k in influencers for k in ("Fed", "FOMC", "Interest Rates", "Interest Rate")):
            return f"בשורה התחתונה: ריבית גבוהה לאורך זמן — לחץ על מניות הצמיחה ועל {assets}."
        if any(k in influencers for k in ("Tariff", "Trade War")):
            return f"בשורה התחתונה: מלחמת סחר — לחץ מכירה צפוי על {assets}, העדפה לנכסי מקלט."
        if any(k in influencers for k in ("CPI", "Inflation")):
            return f"בשורה התחתונה: אינפלציה גבוהה מהצפוי — ירידות בשוקי המניות ועלייה בתשואות האג\"ח."
        return f"בשורה התחתונה: צפי לתנודתיות גבוהה ב-{assets} — שמור על פוזיציות קטנות."


def build_macro_flash_message(flash: MacroFlash) -> str:
    """Build Hebrew Telegram message for a macro / political alert."""
    if flash.reaction == "bullish":
        sentiment_icon  = "📈"
        sentiment_label = "חיובי — כסף זורם לשוק (Risk-On)"
    else:
        sentiment_icon  = "📉"
        sentiment_label = "שלילי — כסף יוצא מהשוק (Risk-Off)"

    assets_str    = " / ".join(flash.affected_assets)
    source_suffix = f" ({flash.source})" if flash.source else ""
    bottom_line   = _build_macro_bottom_line(flash)

    lines = [
        "🏛️ *אירוע מאקרו משמעותי*",
        "🌐 *מבזק מאקרו ופוליטיקה עולמית*",
        "",
        f"💡 *כותרת:* {flash.title}{source_suffix}",
        "",
        f"📝 *ניתוח שוק:* {flash.summary}",
        "",
        f"{sentiment_icon} *סנטימנט:* {sentiment_label}",
        f"📊 *נכסים מושפעים:* {assets_str}",
        "",
        f"🔑 *{bottom_line}*",
        "",
        f"⏰ _{_israel_ts(flash.published_at)}_",
    ]
    return "\n".join(lines)


async def send_macro_flash(flash: MacroFlash, bot_token: str, chat_id: str) -> bool:
    """Send a macro catalyst flash via Telegram. Returns True on success."""
    bot  = Bot(token=bot_token)
    text = build_macro_flash_message(flash)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        return True
    except TelegramError as exc:
        log.warning("send_macro_flash failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Smart Money Alert (Task 25)
# ─────────────────────────────────────────────────────────────────────────────

def build_smart_money_message(alert: InsiderAlert | OptionsFlowAlert) -> str:
    """Build Hebrew Telegram message for an insider purchase or unusual options flow."""
    if isinstance(alert, InsiderAlert):
        value_m = alert.value / 1_000_000
        value_str = f"${value_m:.2f}M" if value_m >= 1 else f"${alert.value:,.0f}"
        lines = [
            "🕵️ *מעקב כסף חכם ודיווחים פנים-ארגוניים*",
            "",
            f"📌 *מניה:* {alert.ticker}",
            f"👤 *בעל תפקיד:* {alert.insider_name} ({alert.position})",
            f"💰 *סוג עסקה:* קנייה פנים-ארגונית",
            f"📊 *כמות מניות:* {alert.shares:,}",
            f"💵 *שווי העסקה:* {value_str}",
            f"📅 *תאריך עסקה:* {alert.transaction_date.strftime('%d/%m/%Y')}",
            f"📋 *מקור:* {alert.source}",
            "",
            "🔑 *ניתוח:* קנייה פנים-ארגונית משמעותית — בעל תפקיד בכיר מגדיל אחזקות. "
            "סימן אפשרי לאמון הנהלה בפוטנציאל המניה.",
            "",
            f"⏰ _{_israel_ts()}_",
        ]
    else:
        # OptionsFlowAlert
        direction_emoji = "🟢" if alert.option_type == "CALL" else "🔴"
        option_heb      = "CALL (ציפייה לעלייה)" if alert.option_type == "CALL" else "PUT (ציפייה לירידה)"
        lines = [
            "🕵️ *מעקב כסף חכם ודיווחים פנים-ארגוניים*",
            "",
            f"📌 *מניה:* {alert.ticker}",
            f"{direction_emoji} *סוג אופציה:* {option_heb}",
            f"🎯 *מחיר מימוש:* ${alert.strike:.1f}",
            f"📅 *פקיעה:* {alert.expiry}",
            f"📊 *נפח מסחר:* {alert.volume:,}  |  OI: {alert.open_interest:,}",
            f"⚡ *יחס Volume/OI:* {alert.volume_oi_ratio:.1f}x",
            f"📋 *מקור:* {alert.source}",
            "",
            f"🔑 *ניתוח:* נפח אופציות חריג — {alert.volume_oi_ratio:.1f}× מעל ה-Open Interest. "
            "פעילות זו מאפיינת 'כסף חכם' שרוכש הגנה או ספקולציה כיוונית לפני אירוע צפוי.",
            "",
            f"⏰ _{_israel_ts()}_",
        ]
    return "\n".join(lines)


async def send_smart_money_alert(
    alert: InsiderAlert | OptionsFlowAlert, bot_token: str, chat_id: str
) -> bool:
    """Send a smart-money (insider/options) alert via Telegram. Returns True on success."""
    bot  = Bot(token=bot_token)
    text = build_smart_money_message(alert)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        return True
    except TelegramError as exc:
        log.warning("send_smart_money_alert failed for %s: %s", alert.ticker, exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Telegram dispatch
# ─────────────────────────────────────────────────────────────────────────────

async def send_alert(
    alert: Alert,
    headlines: list[str],
    bot_token: str,
    chat_id: str,
    debate: DebateResult | None = None,
) -> int | None:
    """Send alert via Telegram with 3 retries.

    When a chart is present the full text is sent first (no caption limit),
    then the chart is sent as a separate photo with a short one-liner caption.
    When *debate* is provided the Agent Council section is appended.
    Returns the message_id of the text message on success, None on failure.
    """
    # ── Hard validation firewall ──────────────────────────────────────────────
    # Reject any call that carries placeholder / error-state data so that
    # technical failures can NEVER produce a Telegram message, regardless of
    # what upstream code does.
    if alert.ticker == "SYSTEM":
        log.error(
            "send_alert BLOCKED: ticker='SYSTEM' — phantom alert suppressed. "
            "This indicates a circuit-breaker or error-handler is calling send_alert incorrectly."
        )
        return None
    if not alert.entry or alert.entry == 0.0:
        log.error(
            "send_alert BLOCKED for %s: entry=0.0 — data integrity check failed, alert suppressed.",
            alert.ticker,
        )
        return None
    if alert.direction == "NEUTRAL":
        log.error(
            "send_alert BLOCKED for %s: direction=NEUTRAL — only LONG/SHORT alerts may be sent.",
            alert.ticker,
        )
        return None

    bot  = Bot(token=bot_token)
    text = build_message(alert, headlines, debate)

    msg_id: int | None = None
    for attempt in range(3):
        try:
            msg = await bot.send_message(
                chat_id=chat_id, text=text, parse_mode="Markdown"
            )
            msg_id = msg.message_id
            break
        except TelegramError:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt * 2)

    if msg_id is None:
        return None

    # Send chart as a follow-up photo with a short caption (no 1,024-char limit issue)
    if alert.chart_path and os.path.exists(alert.chart_path):
        caption = (
            f"📊 {alert.ticker} | {alert.direction} | "
            f"כניסה ${alert.entry:.2f} → TP1 ${alert.take_profit_1 or alert.take_profit:.2f} | "
            f"RSI {alert.rsi:.1f}"
        )
        for attempt in range(3):
            try:
                with open(alert.chart_path, "rb") as photo:
                    await bot.send_photo(
                        chat_id=chat_id, photo=photo,
                        caption=caption,
                        reply_to_message_id=msg_id,
                    )
                break
            except TelegramError:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt * 2)

        # Clean up temporary chart PNG after sending to save disk space
        try:
            os.remove(alert.chart_path)
        except OSError:
            pass

    return msg_id


# ─────────────────────────────────────────────────────────────────────────────
# Learning Report (Task 27)
# ─────────────────────────────────────────────────────────────────────────────

_DAY_NAMES_HEB = {0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי", 4: "שישי", 5: "שבת", 6: "ראשון"}


def build_learning_report_message(report: LearningReport) -> str:
    """Build Hebrew Telegram message for the weekly Self-Learning Report."""
    week_s = report.week_start.strftime("%d/%m/%Y")
    week_e = report.week_end.strftime("%d/%m/%Y")

    lines = [
        "🤖 *דוח למידה עצמית ושיפור אסטרטגיה*",
        "",
        f"📅 *תקופת ניתוח:* {week_s} — {week_e}",
    ]

    # ── No resolved trades ────────────────────────────────────────────────────
    if report.total_trades == 0:
        lines += [
            "",
            "📭 *אין עסקאות מוסכמות השבוע — אין ניתוח להציג.*",
        ]
        if report.unresolved:
            lines.append(f"  ({report.unresolved} עסקאות עדיין פתוחות)")
        lines += ["", f"⏰ _{_israel_ts()}_"]
        return "\n".join(lines)

    # ── Weekly stats block ─────────────────────────────────────────────────────
    win_rate_pct = report.win_rate_before * 100
    lines += [
        "",
        "📊 *סטטיסטיקת השבוע:*",
        f"  סה\"כ עסקאות: `{report.total_trades}`"
        f"  |  ✅ `{report.wins}`  |  ❌ `{report.losses}`",
        f"  אחוז הצלחה: `{win_rate_pct:.1f}%`",
    ]
    if report.unresolved:
        lines.append(f"  עסקאות פתוחות (לא כלולות): `{report.unresolved}`")

    # ── Patterns / insights ────────────────────────────────────────────────────
    if not report.patterns:
        lines += [
            "",
            "✅ *לא זוהו אזורים רעילים השבוע. אין שינויי פילטר.*",
        ]
    else:
        lines += ["", "🔍 *תובנות שזיהיתי:*", ""]
        for i, p in enumerate(report.patterns, 1):
            fail_pct = p.failure_rate * 100
            lines += [
                f"⚠️ *{i}. {p.description_heb}*",
                f"   {p.failed_count}/{p.sample_count} כישלונות ({fail_pct:.0f}%)",
                f"   → {p.action_heb}",
                "",
            ]

        # ── Projected improvement ──────────────────────────────────────────────
        if report.trades_filtered > 0:
            after_pct = report.win_rate_after * 100
            delta_pct = after_pct - win_rate_pct
            lines += [
                "━━━━━━━━━━━━━━━━━━━━━━━━",
                f"🎯 *תחזית לאחר הפילטרים:* `{after_pct:.1f}%` הצלחה",
                f"   (הסרת {report.trades_filtered} עסקאות רעילות"
                + (f" — שיפור של `+{delta_pct:.1f}%`" if delta_pct > 0 else "") + ")",
            ]

    lines += ["", f"⏰ _{_israel_ts()}_"]
    return "\n".join(lines)


async def send_learning_report(report: LearningReport, bot_token: str, chat_id: str) -> bool:
    """Send the weekly Self-Learning Report via Telegram. Returns True on success."""
    bot  = Bot(token=bot_token)
    text = build_learning_report_message(report)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        return True
    except TelegramError as exc:
        log.warning("send_learning_report failed: %s", exc)
        return False


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
        f"⏰ _{_israel_ts()}_",
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
# Morning Brief (08:30 IDT)
# ─────────────────────────────────────────────────────────────────────────────

async def send_morning_brief(text: str, bot_token: str, chat_id: str) -> bool:
    """Send the AI-generated morning brief via Telegram. Returns True on success."""
    if not text.strip():
        log.info("Morning brief: empty text — nothing to send")
        return False
    bot    = Bot(token=bot_token)
    header = (
        "🌅 *Stock Sentinel — דוח בוקר*\n"
        f"⏰ _{_israel_ts()}_\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    try:
        await bot.send_message(
            chat_id=chat_id, text=header + text, parse_mode="Markdown"
        )
        return True
    except TelegramError as exc:
        log.warning("send_morning_brief failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Pre-Market Catalysts (16:20 IDT — 10 min before US open)
# ─────────────────────────────────────────────────────────────────────────────

async def send_premarket_catalysts(text: str, bot_token: str, chat_id: str) -> bool:
    """Send the pre-market catalyst report via Telegram. Returns True on success."""
    if not text.strip():
        log.info("Pre-market catalysts: empty text — channel stays silent")
        return False
    bot    = Bot(token=bot_token)
    header = (
        "⚡ *Stock Sentinel — קטליזטורים לפני פתיחת השוק*\n"
        f"⏰ _{_israel_ts()}_\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    try:
        await bot.send_message(
            chat_id=chat_id, text=header + text, parse_mode="Markdown"
        )
        return True
    except TelegramError as exc:
        log.warning("send_premarket_catalysts failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Daily Performance Report (23:30 IDT — 30 min after US close)
# ─────────────────────────────────────────────────────────────────────────────

def build_daily_performance_report(stats: dict, today_alerts: list[dict]) -> str:
    """Build an enhanced Hebrew daily performance report.

    Includes the standard stats block plus a per-trade prediction-vs-actual table
    derived from the TP/SL hit flags already tracked in the DB.
    """
    total    = stats.get("total", 0)
    wins     = stats.get("wins", 0)
    losses   = stats.get("losses", 0)
    win_rate = stats.get("win_rate", 0.0)
    top_facs = stats.get("top_factors", [])

    lines = [
        "📊 *דוח ביצועים יומי — Stock Sentinel*",
        f"⏰ _{_israel_ts()}_",
        "",
    ]

    if total == 0 and not today_alerts:
        lines.append("📭 *לא נשלחו התראות סחר היום.*")
        return "\n".join(lines)

    # ── Stats block ───────────────────────────────────────────────────────────
    if total > 0:
        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "📈 *סטטיסטיקת היום:*",
            f"  סה\"כ עסקאות: `{total}`  |  ✅ `{wins}` הצלחות  |  ❌ `{losses}` כישלונות",
            f"  🎯 אחוז הצלחה: `{win_rate:.0%}`",
        ]

    if top_facs:
        lines += ["", "🏆 *גורמי מכנס מובילים:*"]
        for i, f in enumerate(top_facs, 1):
            lines.append(f"  {i}. {translate_to_hebrew(f)}")

    # ── Per-trade prediction vs actual ────────────────────────────────────────
    if today_alerts:
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "🔍 *מעקב עסקאות — תחזית מול מציאות:*",
            "",
        ]
        for trade in today_alerts[:12]:
            ticker    = trade.get("ticker", "?")
            direction = trade.get("direction", "?")
            entry     = trade.get("entry_price", 0.0)
            tp1       = trade.get("take_profit_1") or trade.get("take_profit", 0.0)
            sl        = trade.get("stop_loss", 0.0)

            # Direction label
            dir_arrow = "↑" if direction == "LONG" else "↓"

            # Outcome badge from DB hit-flags
            if trade.get("sl_hit"):
                outcome = "❌ SL"
            elif trade.get("tp3_hit"):
                outcome = "🏆 TP3"
            elif trade.get("tp2_hit"):
                outcome = "✅ TP2"
            elif trade.get("tp1_hit"):
                outcome = "✅ TP1"
            else:
                outcome = "⏳ פתוח"

            lines.append(
                f"*{ticker}* {dir_arrow} {direction} | "
                f"כניסה `${entry:.2f}` → יעד `${tp1:.2f}` | סטופ `${sl:.2f}` | {outcome}"
            )

    lines += ["", f"_Stock Sentinel · {_israel_ts()}_"]
    return "\n".join(lines)


async def send_daily_performance_report(
    stats: dict, today_alerts: list[dict], bot_token: str, chat_id: str
) -> bool:
    """Send the enhanced daily performance report via Telegram. Returns True on success."""
    bot  = Bot(token=bot_token)
    text = build_daily_performance_report(stats, today_alerts)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        return True
    except TelegramError as exc:
        log.warning("send_daily_performance_report failed: %s", exc)
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
            f"📊 *סטטוס:* הטרייד נסגר.\n\n"
            f"⏰ _{_israel_ts()}_"
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
            f"📊 *סטטוס:* {status}\n\n"
            f"⏰ _{_israel_ts()}_"
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
