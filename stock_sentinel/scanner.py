"""
Autonomous Market Hunter — Task 17.2
======================================
Scans for high-probability trade candidates every 15 minutes by:
  1. Fetching Top-N market movers (gainers + unusual volume) via yfinance
  2. Filtering by Market Cap > 2B and Volume > 1M
  3. Enforcing a per-ticker 4-hour cooldown (with re-alert exceptions)
  4. Adding 5-10 s random jitter between API calls to avoid rate-limiting
"""

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

import yfinance as yf

from stock_sentinel import config
from stock_sentinel.models import ScannerCandidate

log = logging.getLogger(__name__)

# ── Screener queries used by yfinance.  These are the same slugs used on
#    Yahoo Finance's Screener page.  yf.screen() resolves them at runtime.
_SCREENER_QUERIES = ["day_gainers", "most_actives"]

# Fallback tickers used when yfinance screener is unavailable (e.g. in tests)
_FALLBACK_TICKERS: list[str] = []


# ─────────────────────────────────────────────────────────────────────────────
# Cooldown tracker
# ─────────────────────────────────────────────────────────────────────────────

class ScannerCooldownTracker:
    """Track last-alert metadata per ticker to enforce the 4-hour cooldown.

    Re-alert is allowed if:
      • price has moved > SCANNER_PRICE_MOVE_PCT% from the last alert price, OR
      • ticker has hit a new 52-week high since the last alert.
    """

    def __init__(self) -> None:
        # {ticker: {"alerted_at": datetime, "price": float}}
        self._state: dict[str, dict] = {}

    def should_scan(self, ticker: str, current_price: float, is_52w_high: bool) -> bool:
        """Return True if this ticker is eligible for a new scan/alert."""
        entry = self._state.get(ticker)
        if entry is None:
            return True

        alerted_at: datetime = entry["alerted_at"]
        last_price: float    = entry["price"]
        cooldown = timedelta(hours=config.SCANNER_COOLDOWN_HOURS)

        if datetime.now(timezone.utc) - alerted_at < cooldown:
            # Within cooldown — check exception conditions
            price_move_pct = abs((current_price - last_price) / last_price * 100.0)
            if price_move_pct > config.SCANNER_PRICE_MOVE_PCT:
                return True
            if is_52w_high:
                return True
            return False

        return True

    def mark_alerted(self, ticker: str, price: float) -> None:
        self._state[ticker] = {
            "alerted_at": datetime.now(timezone.utc),
            "price": price,
        }

    def clear(self, ticker: str) -> None:
        self._state.pop(ticker, None)


# ─────────────────────────────────────────────────────────────────────────────
# Market-mover fetcher
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_screener_tickers(query: str, count: int) -> list[str]:
    """Return up to *count* ticker symbols from a yfinance screener query.

    Falls back to an empty list if the API call fails.
    """
    try:
        result = yf.screen(query, count=count)
        quotes = result.get("quotes", []) if result else []
        return [q.get("symbol", "") for q in quotes if q.get("symbol")]
    except Exception as exc:
        log.warning("Screener query '%s' failed: %s", query, exc)
        return []


def _fetch_ticker_info(ticker: str) -> dict | None:
    """Return a dict with price, volume, market_cap, 52w_high for *ticker*.

    Returns None on any error.
    """
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price      = float(getattr(info, "last_price", 0) or 0)
        volume     = int(getattr(info, "three_month_average_volume", 0) or 0)
        # Use today's volume if available
        day_volume = int(getattr(info, "last_volume", 0) or 0)
        if day_volume > 0:
            volume = day_volume
        market_cap = float(getattr(info, "market_cap", 0) or 0)
        high_52w   = float(getattr(info, "year_high", 0) or 0)
        prev_close = float(getattr(info, "previous_close", price) or price)
        change_pct = ((price - prev_close) / prev_close * 100.0) if prev_close else 0.0
        is_52w_high = high_52w > 0 and price >= high_52w * 0.99
        return {
            "price":       price,
            "volume":      volume,
            "market_cap":  market_cap,
            "change_pct":  change_pct,
            "is_52w_high": is_52w_high,
        }
    except Exception as exc:
        log.debug("Info fetch failed for %s: %s", ticker, exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_market_movers(
    top_n: int = config.SCANNER_TOP_N,
    jitter_min: float = config.SCANNER_JITTER_MIN,
    jitter_max: float = config.SCANNER_JITTER_MAX,
) -> list[ScannerCandidate]:
    """Fetch and de-duplicate top market movers from all screener queries.

    Applies jitter between screener API calls to avoid rate-limiting.
    Returns raw candidates without cooldown or fundamental filtering.
    """
    seen: set[str] = set()
    raw: list[str] = []

    for query in _SCREENER_QUERIES:
        tickers = _fetch_screener_tickers(query, top_n)
        for t in tickers:
            if t and t not in seen:
                seen.add(t)
                raw.append(t)
        # Jitter between screener calls
        jitter = random.uniform(jitter_min, jitter_max)
        await asyncio.sleep(jitter)

    candidates: list[ScannerCandidate] = []
    for ticker in raw[:top_n * 2]:   # cap total info fetches
        info = _fetch_ticker_info(ticker)
        if info is None:
            continue
        candidates.append(ScannerCandidate(
            ticker=ticker,
            price=info["price"],
            change_pct=info["change_pct"],
            volume=info["volume"],
            market_cap=info["market_cap"],
            reason="52w_high" if info["is_52w_high"] else (
                "gainer" if info["change_pct"] > 0 else "volume"
            ),
        ))
        # Jitter between individual ticker info calls
        jitter = random.uniform(jitter_min, jitter_max)
        await asyncio.sleep(jitter)

    return candidates


def filter_candidates(
    candidates: list[ScannerCandidate],
    cooldown_tracker: ScannerCooldownTracker,
    *,
    min_market_cap: float = config.SCANNER_MIN_MARKET_CAP,
    min_volume: int       = config.SCANNER_MIN_VOLUME,
) -> list[ScannerCandidate]:
    """Apply fundamental and cooldown filters.

    Keeps candidates where:
      - market_cap > min_market_cap
      - volume     > min_volume
      - cooldown_tracker.should_scan() returns True
    """
    passed: list[ScannerCandidate] = []
    for c in candidates:
        if c.market_cap < min_market_cap:
            log.debug("Scanner skip %s: market_cap %.0fM < 2B", c.ticker, c.market_cap / 1e6)
            continue
        if c.volume < min_volume:
            log.debug("Scanner skip %s: volume %d < 1M", c.ticker, c.volume)
            continue
        is_52w = c.reason == "52w_high"
        if not cooldown_tracker.should_scan(c.ticker, c.price, is_52w):
            log.debug("Scanner skip %s: cooldown active", c.ticker)
            continue
        passed.append(c)

    log.info("Scanner: %d/%d candidates passed filters", len(passed), len(candidates))
    return passed
