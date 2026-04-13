"""Tasks 21.5 / 23: Universal News Catalyst Engine — 24/7 operation.

Three parallel scanning paths:
  1. Watchlist path  — polls yfinance + Google News RSS per watchlist ticker;
                       applies full catalyst keyword list + polarization filter;
                       runs TA confirmation for watchlist tickers.
  2. Discovery path  — polls top financial RSS wires for breaking news;
                       extracts ticker symbols from headlines;
                       applies high-impact-only keyword filter + polarization +
                       market-cap liquidity check (>500 M) for non-watchlist tickers.
  3. Macro path      — same general RSS feed items, but detects MACRO_INFLUENCERS
                       keywords (Trump, Fed, FOMC, CPI, Tariff, etc.) with no
                       ticker required; emits MacroFlash objects affecting SPY/QQQ/DIA.

Return type: tuple[list[NewsFlash], list[MacroFlash]]
"""
import asyncio
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import anthropic
import yfinance as yf

log = logging.getLogger(__name__)

from stock_sentinel.analyzer import compute_signals, fetch_ohlcv
from stock_sentinel.config import (
    MACRO_INFLUENCERS,
    NEWS_CATALYST_KEYWORDS,
    NEWS_DISCOVERY_KEYWORDS,
    NEWS_DISCOVERY_MIN_MARKET_CAP,
    NEWS_SENTIMENT_THRESHOLD,
)
from stock_sentinel.models import MacroFlash, NewsFlash

# ─────────────────────────────────────────────────────────────────────────────
# Sentiment scoring
# ─────────────────────────────────────────────────────────────────────────────

BULLISH_TERMS = {
    "buy", "bullish", "long", "breakout", "upside", "rally", "surge",
    "beat", "upgrade", "climbs", "gains", "rises", "strong", "growth",
}
BEARISH_TERMS = {
    "sell", "bearish", "short", "dump", "downside", "crash", "miss",
    "downgrade", "falls", "drops", "weak", "cut", "loss", "decline",
}

# ─────────────────────────────────────────────────────────────────────────────
# Ticker extraction (discovery mode)
# ─────────────────────────────────────────────────────────────────────────────

_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")

# Common uppercase abbreviations / words that are NOT stock tickers
_TICKER_BLOCKLIST: frozenset[str] = frozenset({
    # Conjunctions, prepositions, articles
    "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF", "IN", "IS", "IT", "MY",
    "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE",
    "AM", "HE", "ME", "HIM", "HER", "WHO", "YOU", "NOT",
    # Common short words
    "ALL", "AND", "ARE", "BUT", "CAN", "DID", "FOR", "GET", "GOT", "HAD",
    "HAS", "HAD", "HIT", "HOW", "ITS", "LET", "MAY", "NEW", "NOW", "OFF",
    "OLD", "OUT", "OWN", "PUT", "RAN", "RUN", "SAW", "SAY", "SEE", "SET",
    "SIT", "SIX", "TEN", "THE", "TOO", "TWO", "USE", "VIA", "WAS", "WAY",
    # Frequent financial-news words
    "ADDS", "ALSO", "BACK", "BEAT", "BEEN", "BILL", "BOTH", "BULL", "BUYS",
    "CALL", "CAME", "CASH", "CHIP", "COAL", "COME", "COST", "CUTS", "DATA",
    "DEAL", "DEBT", "DOWN", "EACH", "EARN", "EVEN", "EVER", "FACE", "FACT",
    "FAIL", "FALL", "FAST", "FILE", "FIRM", "FIVE", "FLAT", "FLOW", "FOOD",
    "FORM", "FOUR", "FREE", "FROM", "FUEL", "FULL", "FUND", "GAIN", "GIVE",
    "GOLD", "GOOD", "GREW", "GROW", "HALF", "HARD", "HAVE", "HEAD", "HELD",
    "HERE", "HIGH", "HIRE", "HOLD", "HOME", "HUGE", "HURT", "INTO", "JUST",
    "KEEP", "KIND", "KNOW", "LAND", "LAST", "LATE", "LEAD", "LEAN", "LESS",
    "LIKE", "LINE", "LIST", "LIVE", "LOAD", "LONG", "LOOK", "LOSE", "LOSS",
    "LOST", "LOVE", "MADE", "MAKE", "MANY", "MARK", "MASS", "MEET", "MILD",
    "MISS", "MOVE", "MUCH", "MUST", "NEAR", "NEED", "NEXT", "NINE", "NONE",
    "NOTE", "ONCE", "ONLY", "OPEN", "OVER", "PACE", "PAID", "PART", "PAST",
    "PATH", "PEAK", "PLAN", "PLAY", "POOR", "POST", "PULL", "PUSH", "RATE",
    "READ", "REAL", "RELY", "RENT", "RISE", "RISK", "ROAD", "ROLE", "ROSE",
    "RULE", "RUSH", "SAFE", "SAID", "SALE", "SAME", "SAVE", "SEEN", "SELF",
    "SELL", "SENT", "SHED", "SHIP", "SHOW", "SHUT", "SIDE", "SIGN", "SIZE",
    "SKIP", "SLOW", "SOFT", "SOME", "SORT", "STAR", "STAY", "STEP", "STOP",
    "SUCH", "SURE", "TAKE", "TALK", "TELL", "TERM", "TEST", "THAN", "THAT",
    "THEM", "THEN", "THEY", "THIS", "TIER", "TIME", "TOLD", "TOLL", "TOOK",
    "TOWN", "TRUE", "TURN", "UNIT", "USED", "VERY", "VIEW", "VOTE", "WAIT",
    "WALK", "WANT", "WARS", "WEEK", "WENT", "WERE", "WHAT", "WHEN", "WHOM",
    "WIDE", "WILL", "WITH", "WORD", "WORK", "YEAR", "YOUR", "ZERO",
    # Finance/market abbreviations
    "ADX", "ATR", "AUD", "BOE", "BOND", "BULL", "BEAR", "CAD", "CEO", "CFO",
    "CHF", "CNY", "COO", "CPI", "CTO", "DOJ", "DJIA", "ECB", "EMA", "EPS",
    "ESG", "ETF", "EUR", "FED", "FTC", "FTSE", "GBP", "GDP", "GBP", "IMF",
    "INC", "INR", "IPO", "JPY", "LTD", "MACD", "MMHG", "MON", "MTD", "NASDAQ",
    "NATO", "NET", "NYSE", "OBV", "OECD", "OPEC", "OBV", "PAR", "PPI", "PRE",
    "PRO", "QTD", "REIT", "REP", "ROE", "ROI", "RSI", "SMA", "SPAC", "TAX",
    "TTM", "USD", "VIX", "VOL", "VWAP", "WTO", "YOY", "YTD", "YTM",
    # Days / months
    "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN",
    "JAN", "FEB", "MAR", "APR", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    # Regulatory / government bodies (appear in headlines but are not tickers)
    "FDA", "SEC", "FTC", "DOJ", "ECB", "BOE", "RBI", "IMF", "WTO", "WHO",
    "NYSE", "NASDAQ", "NATO", "OECD", "OPEC", "CNBC", "MSNBC",
})

# ─────────────────────────────────────────────────────────────────────────────
# Whitelisted financial news feeds — reliable wires only (Task 24.1)
# ─────────────────────────────────────────────────────────────────────────────

_GENERAL_NEWS_FEEDS: list[str] = [
    # Reuters — business wire
    "https://feeds.reuters.com/reuters/businessNews",
    # CNBC — top news
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    # Yahoo Finance — main finance wire only (not blogs / opinion)
    "https://finance.yahoo.com/rss/topfinstories",
    # Wall Street Journal — markets
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    # Financial Times — latest headlines
    "https://www.ft.com/rss/home/us",
]

# Clean display names for known RSS domains → used in flash.source
_FEED_SOURCE_NAMES: dict[str, str] = {
    "feeds.reuters.com":  "Reuters",
    "www.cnbc.com":       "CNBC",
    "finance.yahoo.com":  "Yahoo Finance",
    "feeds.a.dj.com":     "WSJ",
    "www.ft.com":         "Financial Times",
    "news.google.com":    "Google News",
    "finance.google.com": "Google Finance",
}

# ─────────────────────────────────────────────────────────────────────────────
# Translation (Task 24.1)
# ─────────────────────────────────────────────────────────────────────────────

def _translate_to_hebrew(text: str) -> str:
    """Translate *text* from English to Hebrew using deep-translator.

    Falls back to the original text on any failure so the pipeline never
    blocks on a translation error.
    """
    if not text or not text.strip():
        return text
    try:
        from deep_translator import GoogleTranslator  # noqa: PLC0415
        translated = GoogleTranslator(source="auto", target="iw").translate(text)
        return translated if translated else text
    except Exception as exc:
        log.debug("Translation failed (%s) — keeping original: %s", exc, text[:60])
        return text

# ─────────────────────────────────────────────────────────────────────────────
# AI-powered news analysis (Task 21.5 upgrade)
# ─────────────────────────────────────────────────────────────────────────────

def _ai_analyze_news_sync(
    title: str,
    ticker: str,
    keywords: list[str],
    reaction: str,
    ta_context: str = "",
) -> str:
    """Generate a professional Hebrew financial analysis for a news headline.

    Uses Claude Haiku (fast + cheap) as a senior financial analyst.
    Explicitly forbidden from repeating the headline in the output.
    Falls back to a Google-translated title when the Anthropic key is absent
    or the call fails, so the pipeline never blocks.
    """
    from stock_sentinel.config import ANTHROPIC_API_KEY, debate_enabled  # avoid circular

    if not debate_enabled():
        return _translate_to_hebrew(title)

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        direction_heb = "שורי (ציפייה לעלייה)" if reaction == "bullish" else "דובי (ציפייה לירידה)"
        kw_str = ", ".join(keywords[:5])
        ta_line = f"\nהקשר טכני: {ta_context}" if ta_context else ""

        system_prompt = (
            "אתה אנליסט פיננסי בכיר המתמחה בשוק המניות האמריקאי. "
            "אתה כותב ניתוחים קצרים בעברית עסקית קולחת ומקצועית לטובת סוחרים פעילים. "
            "כלל ברזל: אסור לחזור על הכותרת שסופקה — הניתוח מסביר את ה'למה' ואת ההשלכות, לא את ה'מה'. "
            "אם יש כמה נקודות חשובות, השתמש בבולטים (•). "
            "היה תמציתי: עד 4 משפטים קצרים או עד 4 בולטים."
        )

        user_prompt = (
            f"נתח את הידיעה הפיננסית הבאה עבור מניית {ticker}:\n\n"
            f"כותרת (אל תחזור עליה): {title}\n"
            f"סנטימנט: {direction_heb}\n"
            f"קטליזטורים שזוהו: {kw_str}"
            f"{ta_line}\n\n"
            "הסבר את הסיבות הכלכליות מאחורי הידיעה, את ההשלכות על המניה, "
            "ואת מה שהסוחר צריך לדעת. כתוב בעברית בלבד."
        )

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        result = response.content[0].text.strip()
        return result if result else _translate_to_hebrew(title)

    except Exception as exc:
        log.debug("AI news analysis failed for %s: %s", ticker, exc)
        return _translate_to_hebrew(title)


async def _ai_analyze_news(
    title: str,
    ticker: str,
    keywords: list[str],
    reaction: str,
    ta_signal=None,
) -> str:
    """Async wrapper around _ai_analyze_news_sync.

    Accepts an optional TechnicalSignal to enrich the analysis with live TA.
    """
    ta_context = ""
    if ta_signal is not None and ta_signal.direction != "NEUTRAL":
        trend_heb = "עולה" if ta_signal.direction == "LONG" else "יורד"
        ta_context = (
            f"מגמה {trend_heb} | RSI {ta_signal.rsi:.0f} | "
            f"כניסה ${ta_signal.entry:.2f} | איתות {ta_signal.direction}"
        )
    return await asyncio.to_thread(
        _ai_analyze_news_sync, title, ticker, keywords, reaction, ta_context
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scheduled report AI functions
# ─────────────────────────────────────────────────────────────────────────────

def _ai_morning_brief_sync(items: list[dict], watchlist: list[str]) -> str:
    """Generate a structured Hebrew morning brief from the most recent news items.

    Falls back to a simple translated bullet list when the Anthropic key is absent.
    """
    from stock_sentinel.config import ANTHROPIC_API_KEY, debate_enabled  # avoid circular

    if not debate_enabled() or not items:
        lines = ["🌅 *סיכום לילה:*", ""]
        for item in items[:10]:
            lines.append(f"• {_translate_to_hebrew(item.get('title', ''))}")
        return "\n".join(lines)

    try:
        client       = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        watchlist_str = ", ".join(watchlist[:12])
        headlines_block = "\n".join(
            f"- {item.get('title', '')} ({item.get('source', '')})"
            for item in items[:15]
        )
        system_prompt = (
            "אתה אנליסט פיננסי בכיר המכין דוח בוקר יומי לסוחרים פעילים בשוק המניות האמריקאי. "
            "כתוב בעברית עסקית קולחת. "
            "הדוח מובנה, ממוקד, ומדגיש אירועים שישפיעו על המסחר של היום."
        )
        user_prompt = (
            f"הכן דוח בוקר יומי בעברית עבור הסוחרים שלי.\n\n"
            f"מניות תחת מעקב: {watchlist_str}\n\n"
            f"חדשות מהלילה:\n{headlines_block}\n\n"
            "הנחיות:\n"
            "1. פתח עם ברכת בוקר קצרה וסנטימנט השוק הכללי (🟢 שורי / 🔴 דובי).\n"
            "2. סכם 4–6 אירועים מרכזיים שישפיעו על המסחר — כל אחד בשורה עם מניה רלוונטית (אם ידועה), "
            "הסבר קצר, ו-🟢/🔴.\n"
            "3. סיים בשורת 'נקודות מפתח לפתיחת השוק' — משפט אחד.\n"
            "כתוב בעברית בלבד. אל תציין מחירים ספציפיים שלא סופקו."
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        result = response.content[0].text.strip()
        return result if result else ""
    except Exception as exc:
        log.warning("AI morning brief failed: %s", exc)
        return ""


def _ai_premarket_catalysts_sync(items: list[dict]) -> str:
    """Filter high-impact pre-market catalysts and return a Hebrew ranked report.

    Falls back to a simple scored bullet list without AI.
    """
    from stock_sentinel.config import ANTHROPIC_API_KEY, debate_enabled

    # Pre-filter to high-impact items only
    HIGH_IMPACT_KWS = {
        "earnings", "fda", "acquisition", "merger", "upgrade", "downgrade",
        "beat", "miss", "approval", "guidance", "buyout", "lawsuit", "settlement",
        "layoffs", "dividend", "revenue", "forecast",
    }
    filtered = [
        item for item in items
        if any(kw in item.get("title", "").lower() for kw in HIGH_IMPACT_KWS)
    ]
    if not filtered:
        filtered = items[:12]  # fallback: use top items

    if not debate_enabled() or not filtered:
        lines = ["⚡ *קטליזטורים לפני פתיחת השוק:*", ""]
        for item in filtered[:12]:
            score = _score_headline(item.get("title", ""))
            emoji = "🟢" if score > 0 else "🔴"
            lines.append(f"{emoji} {_translate_to_hebrew(item.get('title', ''))}")
        return "\n".join(lines)

    try:
        client          = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        headlines_block = "\n".join(
            f"- {item.get('title', '')} ({item.get('source', '')})"
            for item in filtered[:15]
        )
        system_prompt = (
            "אתה אנליסט פיננסי בכיר המתמחה בזיהוי קטליזטורים לפני פתיחת שוק המניות האמריקאי. "
            "עבודתך: לסנן ולדרג ידיעות לפי פוטנציאל תנודתיות — מהגבוה לנמוך. "
            "כתוב בעברית עסקית. עבור כל קטליזטור: 🟢 (שורי) / 🔴 (דובי)."
        )
        user_prompt = (
            "סנן וניתח את הקטליזטורים הבאים לפני פתיחת השוק:\n\n"
            f"{headlines_block}\n\n"
            "הנחיות:\n"
            "1. בחר 5–10 קטליזטורים בעלי ההשפעה הגבוהה ביותר על מחירי המניות.\n"
            "2. עבור כל קטליזטור: 🟢/🔴 | שם המניה (אם ידוע) | הסבר קצר של ה'למה' — שורה אחת.\n"
            "3. דרג מהגבוה לנמוך לפי רמת ההשפעה הצפויה.\n"
            "כתוב בעברית בלבד."
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        result = response.content[0].text.strip()
        return result if result else ""
    except Exception as exc:
        log.warning("AI pre-market catalysts failed: %s", exc)
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Public: scheduled report cycle runners
# ─────────────────────────────────────────────────────────────────────────────

async def run_morning_brief_cycle(watchlist: list[str]) -> str:
    """Fetch recent news from all sources and generate a Hebrew morning brief.

    Intended to run at 08:30 IDT (01:30 ET) before the Israeli trading day begins.
    Returns the formatted Hebrew text, or '' if nothing newsworthy was found.
    """
    all_items: list[dict] = []
    all_items.extend(await asyncio.to_thread(_fetch_general_news))
    for ticker in watchlist[:6]:          # cap to avoid rate limits
        all_items.extend(await asyncio.to_thread(_fetch_yfinance_news, ticker))
        await asyncio.sleep(0)            # yield to event loop

    seen: set[str] = set()
    unique: list[dict] = []
    for item in all_items:
        title = item.get("title", "").strip()
        if title and title not in seen:
            seen.add(title)
            unique.append(item)

    if not unique:
        log.info("Morning brief: no news items found")
        return ""

    log.info("Morning brief: %d unique items — generating AI summary", len(unique))
    return await asyncio.to_thread(_ai_morning_brief_sync, unique[:20], watchlist)


async def run_premarket_catalysts_cycle(watchlist: list[str]) -> str:
    """Fetch news and extract ranked high-impact pre-market catalysts.

    Intended to run at 16:20 IDT (09:20 ET) — 10 minutes before US market open.
    Returns the formatted Hebrew text, or '' if no catalysts qualify.
    """
    all_items: list[dict] = []
    all_items.extend(await asyncio.to_thread(_fetch_general_news))
    for ticker in watchlist[:6]:
        all_items.extend(await asyncio.to_thread(_fetch_yfinance_news, ticker))
        await asyncio.sleep(0)

    seen: set[str] = set()
    unique: list[dict] = []
    for item in all_items:
        title = item.get("title", "").strip()
        if title and title not in seen:
            seen.add(title)
            unique.append(item)

    if not unique:
        log.info("Pre-market catalysts: no news items found")
        return ""

    log.info("Pre-market catalysts: %d items — generating AI catalyst report", len(unique))
    return await asyncio.to_thread(_ai_premarket_catalysts_sync, unique)


_TICKER_RSS_TEMPLATE = (
    "https://news.google.com/rss/search"
    "?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockSentinel/1.0)"}


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

class NewsEngineState:
    """Tracks seen item IDs, warm-up state, and per-ticker liquidity cache."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._liquidity: dict[str, bool] = {}
        self._warmed_up: bool = False   # True after first cycle completes

    # ── warm-up / first-cycle silence ─────────────────────────────────────
    @property
    def warmed_up(self) -> bool:
        return self._warmed_up

    def mark_warmed_up(self) -> None:
        self._warmed_up = True

    # ── dedup ──────────────────────────────────────────────────────────────
    def is_seen(self, item_id: str) -> bool:
        return item_id in self._seen

    def mark_seen(self, item_id: str) -> None:
        self._seen.add(item_id)

    def clear(self) -> None:
        self._seen.clear()
        self._liquidity.clear()
        self._warmed_up = False

    # ── liquidity cache ────────────────────────────────────────────────────
    def has_liquidity_cache(self, ticker: str) -> bool:
        return ticker in self._liquidity

    def get_liquidity_cache(self, ticker: str) -> bool:
        return self._liquidity.get(ticker, False)

    def set_liquidity_cache(self, ticker: str, passes: bool) -> None:
        self._liquidity[ticker] = passes


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _matches_catalyst(title: str, keywords: list[str]) -> list[str]:
    """Return the subset of *keywords* found in *title* (case-insensitive)."""
    lower = title.lower()
    return [kw for kw in keywords if kw.lower() in lower]


def _matches_macro(title: str) -> list[str]:
    """Return MACRO_INFLUENCERS terms found in *title* (case-insensitive)."""
    lower = title.lower()
    return [kw for kw in MACRO_INFLUENCERS if kw.lower() in lower]


def _score_headline(title: str) -> float:
    """Score a single headline in [-1, +1] using bullish/bearish term counts."""
    lower = title.lower()
    bull  = sum(1 for w in BULLISH_TERMS if w in lower)
    bear  = sum(1 for w in BEARISH_TERMS if w in lower)
    total = bull + bear
    return 0.0 if total == 0 else (bull - bear) / total


def _is_polarized(score: float) -> bool:
    """True when |score| exceeds NEWS_SENTIMENT_THRESHOLD."""
    return abs(score) > NEWS_SENTIMENT_THRESHOLD


def _extract_tickers(text: str) -> list[str]:
    """Extract candidate US stock ticker symbols from *text*.

    Uses a regex for 2-5 uppercase letters, then filters the blocklist.
    Returns up to 10 candidates preserving order of appearance.
    """
    seen: set[str] = set()
    result: list[str] = []
    for m in _TICKER_RE.finditer(text):
        sym = m.group(1)
        if sym in _TICKER_BLOCKLIST or sym in seen:
            continue
        seen.add(sym)
        result.append(sym)
        if len(result) == 10:
            break
    return result


def _get_market_cap(ticker: str) -> float:
    """Return market cap in USD for *ticker*; 0.0 on any failure (sync)."""
    try:
        fi = yf.Ticker(ticker).fast_info
        return getattr(fi, "market_cap", 0.0) or 0.0
    except Exception:
        return 0.0


async def _check_liquidity(
    ticker: str,
    state: NewsEngineState,
    min_cap: float,
) -> bool:
    """Return True if *ticker* has market_cap >= *min_cap*.

    Results are cached in *state* so the same ticker is only queried once
    per engine session.
    """
    if state.has_liquidity_cache(ticker):
        return state.get_liquidity_cache(ticker)
    cap = await asyncio.to_thread(_get_market_cap, ticker)
    result = cap >= min_cap
    state.set_liquidity_cache(ticker, result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# News fetchers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_yfinance_news(ticker: str) -> list[dict]:
    """Return up to 20 raw yfinance news items for *ticker*.

    Each item: {title, url, item_id, source}.
    """
    try:
        news = yf.Ticker(ticker).news or []
        items: list[dict] = []
        for item in news[:20]:
            content  = item.get("content") or {}
            title    = content.get("title") or item.get("title", "")
            if not title:
                continue
            canonical = content.get("canonicalUrl") or {}
            url = (canonical.get("url", "") if isinstance(canonical, dict) else "")
            if not url:
                url = item.get("link", "")
            item_id  = item.get("id") or item.get("uuid") or url or title
            provider = content.get("provider") or {}
            source   = provider.get("displayName", "yfinance") if isinstance(provider, dict) else "yfinance"
            items.append({"title": title, "url": url, "item_id": item_id, "source": source})
        return items
    except Exception:
        return []


def _fetch_rss_news(ticker: str) -> list[dict]:
    """Return up to 20 Google News RSS items for *ticker*.

    Each item: {title, url, item_id, source}.
    """
    try:
        url = _TICKER_RSS_TEMPLATE.format(ticker=ticker)
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            tree = ET.parse(resp)
        items: list[dict] = []
        for el in tree.findall(".//item")[:20]:
            title = el.findtext("title", default="")
            link  = el.findtext("link",  default="")
            guid  = el.findtext("guid",  default="")
            if not title:
                continue
            item_id = guid or link or title
            source  = el.findtext("source", default="Google News")
            items.append({"title": title, "url": link, "item_id": item_id, "source": source})
        return items
    except Exception:
        return []


def _fetch_general_news() -> list[dict]:
    """Fetch items from general financial RSS wires.

    Combines results from all configured feeds; failures per-feed are silent.
    Each item: {title, url, item_id, source}.
    """
    combined: list[dict] = []
    for feed_url in _GENERAL_NEWS_FEEDS:
        try:
            req = urllib.request.Request(feed_url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                tree = ET.parse(resp)
            for el in tree.findall(".//item")[:20]:
                title  = el.findtext("title", default="")
                link   = el.findtext("link",  default="")
                guid   = el.findtext("guid",  default="")
                source_tag = el.find("source")
                _domain = feed_url.split("/")[2]
                source = (source_tag.text if source_tag is not None and source_tag.text
                          else _FEED_SOURCE_NAMES.get(_domain, _domain))
                if not title:
                    continue
                item_id = guid or link or title
                combined.append({"title": title, "url": link, "item_id": item_id, "source": source})
        except Exception:
            pass  # one feed down is not fatal
    return combined


# ─────────────────────────────────────────────────────────────────────────────
# Main cycle
# ─────────────────────────────────────────────────────────────────────────────

async def run_news_engine_cycle(
    watchlist: list[str],
    engine_state: NewsEngineState,
) -> tuple[list[NewsFlash], list[MacroFlash]]:
    """Poll all sources; emit NewsFlash and MacroFlash objects for new catalyst hits.

    Path 1 — Watchlist: fetch ticker-specific news; apply full catalyst keyword
              list + polarization filter; enrich with TA confirmation.

    Path 2 — Discovery: fetch general financial RSS wires; extract ticker
              symbols; apply HIGH-IMPACT keyword filter + polarization + market
              cap liquidity check for non-watchlist tickers.

    Path 3 — Macro: same general feed items; match MACRO_INFLUENCERS keywords
              (Fed/FOMC/CPI/Trump/Tariff …); no ticker required; default
              affected assets = SPY, QQQ, DIA.

    Returns (news_flashes, macro_flashes) — both may be empty.
    """
    watchlist_set = set(watchlist)
    flashes: list[NewsFlash] = []
    macro_flashes: list[MacroFlash] = []

    # ── First-cycle warm-up (anti-flood): mark everything seen, emit nothing ──
    # On the very first call after startup the seen-set is empty — every stored
    # article would fire.  We prime the dedup set without alerting so only
    # genuinely NEW items (arriving after the first poll) produce messages.
    warming_up = not engine_state.warmed_up

    # ── Path 1: Watchlist ────────────────────────────────────────────────────
    for ticker in watchlist:
        raw_items: list[dict] = []
        raw_items.extend(_fetch_yfinance_news(ticker))
        raw_items.extend(_fetch_rss_news(ticker))

        for raw in raw_items:
            item_id = raw["item_id"]
            if engine_state.is_seen(item_id):
                continue

            title   = raw["title"]
            matched = _matches_catalyst(title, NEWS_CATALYST_KEYWORDS)
            if not matched:
                engine_state.mark_seen(item_id)
                continue

            score = _score_headline(title)
            if not _is_polarized(score):
                engine_state.mark_seen(item_id)
                continue

            engine_state.mark_seen(item_id)

            if warming_up:
                continue   # silently prime the dedup set

            reaction = "bullish" if score > 0 else "bearish"

            # Translate title to Hebrew
            title_heb = await asyncio.to_thread(_translate_to_hebrew, title)

            flash = NewsFlash(
                ticker=ticker,
                title=title_heb,
                summary=title_heb,
                url=raw["url"],
                source=raw["source"],
                sentiment_score=score,
                catalyst_keywords=matched,
                reaction=reaction,
                is_watchlist=True,
                item_id=item_id,
            )

            # Fetch TA for context (failure is non-fatal — AI runs with or without it)
            ta_signal = None
            try:
                df        = await asyncio.to_thread(fetch_ohlcv, ticker)
                ta_signal = await asyncio.to_thread(compute_signals, ticker, df)
            except Exception:
                pass

            # AI-powered analysis — passes original English title so the model
            # reasons on clean input; flash.title stays as the Hebrew translation.
            flash.summary = await _ai_analyze_news(
                title=title,
                ticker=ticker,
                keywords=matched,
                reaction=reaction,
                ta_signal=ta_signal,
            )

            flashes.append(flash)

        await asyncio.sleep(0)

    # ── Path 2: Universal Discovery ──────────────────────────────────────────
    general_items = await asyncio.to_thread(_fetch_general_news)

    for raw in general_items:
        item_id = raw["item_id"]
        if engine_state.is_seen(item_id):
            continue

        title = raw["title"]

        candidates = [t for t in _extract_tickers(title) if t not in watchlist_set]
        if not candidates:
            continue  # no ticker — let Macro path evaluate

        matched_hik = _matches_catalyst(title, NEWS_DISCOVERY_KEYWORDS)
        if not matched_hik:
            continue  # no high-impact keyword — let Macro path evaluate

        score = _score_headline(title)
        if not _is_polarized(score):
            engine_state.mark_seen(item_id)
            continue

        engine_state.mark_seen(item_id)

        if warming_up:
            continue

        reaction = "bullish" if score > 0 else "bearish"

        winning_ticker: str | None = None
        for cand in candidates[:5]:
            if await _check_liquidity(cand, engine_state, NEWS_DISCOVERY_MIN_MARKET_CAP):
                winning_ticker = cand
                break

        if not winning_ticker:
            continue

        title_heb  = await asyncio.to_thread(_translate_to_hebrew, title)
        ai_summary = await _ai_analyze_news(
            title=title,
            ticker=winning_ticker,
            keywords=matched_hik,
            reaction=reaction,
        )

        flash = NewsFlash(
            ticker=winning_ticker,
            title=title_heb,
            summary=ai_summary,
            url=raw["url"],
            source=raw["source"],
            sentiment_score=score,
            catalyst_keywords=matched_hik,
            reaction=reaction,
            is_watchlist=False,
            item_id=item_id,
        )
        flashes.append(flash)

    # ── Path 3: Macro / Political ────────────────────────────────────────────
    for raw in general_items:
        item_id = raw["item_id"]
        if engine_state.is_seen(item_id):
            continue

        title = raw["title"]

        matched_macro = _matches_macro(title)
        if not matched_macro:
            engine_state.mark_seen(item_id)
            continue

        score = _score_headline(title)
        if not _is_polarized(score):
            engine_state.mark_seen(item_id)
            continue

        engine_state.mark_seen(item_id)

        if warming_up:
            continue

        reaction = "bullish" if score > 0 else "bearish"

        title_heb     = await asyncio.to_thread(_translate_to_hebrew, title)
        influencer_str = " / ".join(matched_macro[:3])
        direction_heb  = "חיובי (Risk-On)" if reaction == "bullish" else "שלילי (Risk-Off)"
        summary = (
            f"{title_heb}. "
            f"האירוע קשור ל-{influencer_str} ועשוי להשפיע על כיוון השוק הכללי — "
            f"סנטימנט {direction_heb}."
        )

        macro_flashes.append(MacroFlash(
            title=title_heb,
            summary=summary,
            url=raw["url"],
            source=raw["source"],
            sentiment_score=score,
            influencers=matched_macro,
            reaction=reaction,
            item_id=item_id,
        ))

    # Mark warm-up complete after first cycle
    if warming_up:
        engine_state.mark_warmed_up()
        log.info("News engine warm-up complete — %d items primed, alerts now live", len(engine_state._seen))

    return flashes, macro_flashes
