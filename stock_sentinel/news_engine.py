"""Task 19: Real-time News Catalyst Engine.

Polls yfinance + Google News RSS for every watchlist ticker every 5 minutes.
Filters for catalyst keywords and sentiment polarization, then optionally
runs a fast TA check for watchlist tickers to confirm trade entry formation.
"""
import asyncio
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import yfinance as yf

from stock_sentinel.analyzer import compute_signals, fetch_ohlcv
from stock_sentinel.config import NEWS_CATALYST_KEYWORDS, NEWS_SENTIMENT_THRESHOLD
from stock_sentinel.models import NewsFlash

BULLISH_TERMS = {
    "buy", "bullish", "long", "breakout", "upside", "rally", "surge",
    "beat", "upgrade", "climbs", "gains", "rises", "strong", "growth",
}
BEARISH_TERMS = {
    "sell", "bearish", "short", "dump", "downside", "crash", "miss",
    "downgrade", "falls", "drops", "weak", "cut", "loss", "decline",
}

_RSS_TEMPLATE = (
    "https://news.google.com/rss/search"
    "?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockSentinel/1.0)"}


class NewsEngineState:
    """Tracks seen item IDs to prevent duplicate news flash alerts."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_seen(self, item_id: str) -> bool:
        return item_id in self._seen

    def mark_seen(self, item_id: str) -> None:
        self._seen.add(item_id)

    def clear(self) -> None:
        self._seen.clear()


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


def _fetch_yfinance_news(ticker: str) -> list[dict]:
    """Return up to 20 raw yfinance news items for *ticker*.

    Each item is a dict with keys: title, url, item_id, source.
    Returns [] on any failure.
    """
    try:
        news = yf.Ticker(ticker).news or []
        items: list[dict] = []
        for item in news[:20]:
            content = item.get("content") or {}
            title   = content.get("title") or item.get("title", "")
            if not title:
                continue
            # Resolve URL from nested structure or top-level link
            canonical = content.get("canonicalUrl") or {}
            url = (canonical.get("url", "") if isinstance(canonical, dict) else "")
            if not url:
                url = item.get("link", "")
            item_id = item.get("id") or item.get("uuid") or url or title
            provider = content.get("provider") or {}
            source   = provider.get("displayName", "yfinance") if isinstance(provider, dict) else "yfinance"
            items.append({"title": title, "url": url, "item_id": item_id, "source": source})
        return items
    except Exception:
        return []


def _fetch_rss_news(ticker: str) -> list[dict]:
    """Return up to 20 Google News RSS items for *ticker*.

    Each item is a dict with keys: title, url, item_id, source.
    Returns [] on any failure.
    """
    try:
        url = _RSS_TEMPLATE.format(ticker=ticker)
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


async def run_news_engine_cycle(
    watchlist: list[str],
    engine_state: NewsEngineState,
) -> list[NewsFlash]:
    """Poll all sources for every ticker, emit NewsFlash objects for new catalyst hits.

    Algorithm per ticker per item:
      1. Skip if item_id already seen.
      2. Skip if no catalyst keyword matched.
      3. Skip if sentiment not polarized (|score| <= threshold).
      4. For watchlist tickers: attempt fast TA confirmation via compute_signals.
      5. Build and return a NewsFlash.

    Returns list of new NewsFlash objects for this cycle (may be empty).
    """
    flashes: list[NewsFlash] = []

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
                summary=title,   # default; enriched below when TA succeeds
                url=raw["url"],
                source=raw["source"],
                sentiment_score=score,
                catalyst_keywords=matched,
                reaction=reaction,
                item_id=item_id,
            )

            # ── Watchlist TA correlation ──────────────────────────────────────
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
                pass  # TA failure — keep the title-only summary

            flashes.append(flash)

        # Yield to the event loop between tickers
        await asyncio.sleep(0)

    return flashes
