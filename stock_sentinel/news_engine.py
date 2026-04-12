"""Task 21.5: Universal News Catalyst Engine — 24/7 operation.

Two parallel scanning paths:
  1. Watchlist path  — polls yfinance + Google News RSS per watchlist ticker;
                       applies full catalyst keyword list + polarization filter;
                       runs TA confirmation for watchlist tickers.
  2. Discovery path  — polls top financial RSS wires for breaking news;
                       extracts ticker symbols from headlines;
                       applies high-impact-only keyword filter + polarization +
                       market-cap liquidity check (>500 M) for non-watchlist tickers.
"""
import asyncio
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import yfinance as yf

from stock_sentinel.analyzer import compute_signals, fetch_ohlcv
from stock_sentinel.config import (
    NEWS_CATALYST_KEYWORDS,
    NEWS_DISCOVERY_KEYWORDS,
    NEWS_DISCOVERY_MIN_MARKET_CAP,
    NEWS_SENTIMENT_THRESHOLD,
)
from stock_sentinel.models import NewsFlash

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
# General financial news feeds (discovery mode)
# ─────────────────────────────────────────────────────────────────────────────

_GENERAL_NEWS_FEEDS: list[str] = [
    "https://finance.yahoo.com/rss/topfinstories",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.marketwatch.com/rss/topstories",
]

_TICKER_RSS_TEMPLATE = (
    "https://news.google.com/rss/search"
    "?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockSentinel/1.0)"}


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

class NewsEngineState:
    """Tracks seen item IDs and caches per-ticker liquidity results."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._liquidity: dict[str, bool] = {}

    # ── dedup ──────────────────────────────────────────────────────────────
    def is_seen(self, item_id: str) -> bool:
        return item_id in self._seen

    def mark_seen(self, item_id: str) -> None:
        self._seen.add(item_id)

    def clear(self) -> None:
        self._seen.clear()
        self._liquidity.clear()

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
    return [kw for kw in keywords if kw in lower]


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
                source = (source_tag.text if source_tag is not None and source_tag.text
                          else feed_url.split("/")[2])  # domain as fallback
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
) -> list[NewsFlash]:
    """Poll all sources, emit NewsFlash objects for new catalyst hits.

    Path 1 — Watchlist: fetch ticker-specific news; apply full catalyst keyword
              list + polarization filter; enrich with TA confirmation.

    Path 2 — Discovery: fetch general financial RSS wires; extract ticker
              symbols; apply HIGH-IMPACT keyword filter + polarization + market
              cap liquidity check for non-watchlist tickers.

    Returns list of new NewsFlash objects (may be empty).
    """
    watchlist_set = set(watchlist)
    flashes: list[NewsFlash] = []

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

            reaction = "bullish" if score > 0 else "bearish"
            engine_state.mark_seen(item_id)

            flash = NewsFlash(
                ticker=ticker,
                title=title,
                summary=title,
                url=raw["url"],
                source=raw["source"],
                sentiment_score=score,
                catalyst_keywords=matched,
                reaction=reaction,
                is_watchlist=True,
                item_id=item_id,
            )

            # TA confirmation
            try:
                df     = await asyncio.to_thread(fetch_ohlcv, ticker)
                signal = await asyncio.to_thread(compute_signals, ticker, df)
                if signal.direction != "NEUTRAL":
                    trend = "עולה" if signal.direction == "LONG" else "יורד"
                    flash.summary = (
                        f"{title}. "
                        f"הניתוח הטכני מצביע על מגמה {trend} "
                        f"עם RSI {signal.rsi:.0f} ואיתות {signal.direction}."
                    )
                else:
                    flash.summary = f"{title}. אין אישור טכני לכניסה בשלב זה."
            except Exception:
                pass  # keep title-only summary

            flashes.append(flash)

        await asyncio.sleep(0)

    # ── Path 2: Universal Discovery ──────────────────────────────────────────
    general_items = await asyncio.to_thread(_fetch_general_news)

    for raw in general_items:
        item_id = raw["item_id"]
        if engine_state.is_seen(item_id):
            continue

        title = raw["title"]

        # Extract non-watchlist ticker candidates (watchlist tickers already
        # handled in Path 1; skip them here to avoid duplicates)
        candidates = [t for t in _extract_tickers(title) if t not in watchlist_set]
        if not candidates:
            engine_state.mark_seen(item_id)
            continue

        # High-impact keyword filter (stricter than watchlist path)
        matched_hik = _matches_catalyst(title, NEWS_DISCOVERY_KEYWORDS)
        if not matched_hik:
            engine_state.mark_seen(item_id)
            continue

        # Polarization filter
        score = _score_headline(title)
        if not _is_polarized(score):
            engine_state.mark_seen(item_id)
            continue

        reaction = "bullish" if score > 0 else "bearish"
        engine_state.mark_seen(item_id)

        # Liquidity check: first candidate that passes wins
        winning_ticker: str | None = None
        for cand in candidates[:5]:   # cap at 5 yfinance calls per item
            if await _check_liquidity(cand, engine_state, NEWS_DISCOVERY_MIN_MARKET_CAP):
                winning_ticker = cand
                break

        if not winning_ticker:
            continue

        flash = NewsFlash(
            ticker=winning_ticker,
            title=title,
            summary=title,
            url=raw["url"],
            source=raw["source"],
            sentiment_score=score,
            catalyst_keywords=matched_hik,
            reaction=reaction,
            is_watchlist=False,
            item_id=item_id,
        )
        flashes.append(flash)

    return flashes
