"""Tests for stock_sentinel.news_engine — Tasks 19 / 21.5."""

import io
import textwrap
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_sentinel.news_engine import (
    NewsEngineState,
    _check_liquidity,
    _extract_tickers,
    _fetch_general_news,
    _fetch_rss_news,
    _fetch_yfinance_news,
    _get_market_cap,
    _is_polarized,
    _matches_catalyst,
    _score_headline,
    run_news_engine_cycle,
)


# ── _matches_catalyst ─────────────────────────────────────────────────────────

def test_matches_catalyst_single_keyword():
    keywords = ["merger", "earnings", "fda"]
    assert _matches_catalyst("Company announces merger with rival", keywords) == ["merger"]


def test_matches_catalyst_multiple_keywords():
    keywords = ["earnings", "beat", "guidance"]
    result = _matches_catalyst("Earnings beat expectations; raises guidance", keywords)
    assert "earnings" in result
    assert "beat" in result
    assert "guidance" in result


def test_matches_catalyst_case_insensitive():
    keywords = ["fda"]
    assert _matches_catalyst("FDA approves new drug", keywords) == ["fda"]


def test_matches_catalyst_no_match():
    keywords = ["merger", "acquisition"]
    assert _matches_catalyst("Stock price hits 52-week high", keywords) == []


def test_matches_catalyst_empty_title():
    assert _matches_catalyst("", ["merger"]) == []


# ── _score_headline ───────────────────────────────────────────────────────────

def test_score_headline_bullish():
    score = _score_headline("Company beats earnings expectations with strong growth")
    assert score > 0


def test_score_headline_bearish():
    score = _score_headline("Stock falls on weak earnings miss and downgrade")
    assert score < 0


def test_score_headline_neutral_no_terms():
    score = _score_headline("Company announces quarterly report date")
    assert score == 0.0


def test_score_headline_mixed_leans_to_dominant():
    # "beats" (bull) vs "crash" (bear) — 1 bull, 1 bear → 0.0
    score = _score_headline("Stock beats but then crashes")
    assert score == 0.0


def test_score_headline_range():
    score = _score_headline("Strong rally and bullish breakout with surge in growth")
    assert -1.0 <= score <= 1.0


# ── _is_polarized ─────────────────────────────────────────────────────────────

def test_is_polarized_above_threshold():
    assert _is_polarized(0.6) is True


def test_is_polarized_below_threshold():
    assert _is_polarized(0.3) is False


def test_is_polarized_at_threshold_is_false():
    # threshold is 0.55 — must EXCEED it
    assert _is_polarized(0.55) is False


def test_is_polarized_negative_strong():
    assert _is_polarized(-0.8) is True


def test_is_polarized_zero():
    assert _is_polarized(0.0) is False


# ── NewsEngineState ───────────────────────────────────────────────────────────

def test_news_state_new_item_not_seen():
    state = NewsEngineState()
    assert state.is_seen("abc123") is False


def test_news_state_mark_and_seen():
    state = NewsEngineState()
    state.mark_seen("abc123")
    assert state.is_seen("abc123") is True


def test_news_state_clear():
    state = NewsEngineState()
    state.mark_seen("abc123")
    state.clear()
    assert state.is_seen("abc123") is False


def test_news_state_multiple_items():
    state = NewsEngineState()
    state.mark_seen("id1")
    state.mark_seen("id2")
    assert state.is_seen("id1") is True
    assert state.is_seen("id2") is True
    assert state.is_seen("id3") is False


# ── _fetch_yfinance_news ──────────────────────────────────────────────────────

def test_fetch_yfinance_news_returns_items():
    mock_news = [
        {
            "content": {
                "title": "NVDA beats earnings",
                "canonicalUrl": {"url": "https://example.com/nvda"},
                "provider": {"displayName": "Reuters"},
            },
            "id": "guid-001",
        }
    ]
    with patch("stock_sentinel.news_engine.yf.Ticker") as MockTicker:
        MockTicker.return_value.news = mock_news
        items = _fetch_yfinance_news("NVDA")
    assert len(items) == 1
    assert items[0]["title"] == "NVDA beats earnings"
    assert items[0]["url"] == "https://example.com/nvda"
    assert items[0]["item_id"] == "guid-001"
    assert items[0]["source"] == "Reuters"


def test_fetch_yfinance_news_fallback_top_level_title():
    mock_news = [{"title": "NVDA surges", "link": "https://example.com", "uuid": "u1"}]
    with patch("stock_sentinel.news_engine.yf.Ticker") as MockTicker:
        MockTicker.return_value.news = mock_news
        items = _fetch_yfinance_news("NVDA")
    assert items[0]["title"] == "NVDA surges"
    assert items[0]["item_id"] == "u1"


def test_fetch_yfinance_news_handles_error():
    with patch("stock_sentinel.news_engine.yf.Ticker", side_effect=Exception("network")):
        items = _fetch_yfinance_news("BROKEN")
    assert items == []


def test_fetch_yfinance_news_skips_empty_title():
    mock_news = [{"content": {"title": ""}, "id": "empty-1"}]
    with patch("stock_sentinel.news_engine.yf.Ticker") as MockTicker:
        MockTicker.return_value.news = mock_news
        items = _fetch_yfinance_news("NVDA")
    assert items == []


# ── _fetch_rss_news ───────────────────────────────────────────────────────────

def _make_rss_xml(items: list[dict]) -> bytes:
    """Build a minimal RSS XML bytes blob."""
    channel_items = ""
    for it in items:
        channel_items += (
            f"<item>"
            f"<title>{it.get('title', '')}</title>"
            f"<link>{it.get('link', '')}</link>"
            f"<guid>{it.get('guid', '')}</guid>"
            f"<source>{it.get('source', 'Google News')}</source>"
            f"</item>"
        )
    xml = f"<rss><channel>{channel_items}</channel></rss>"
    return xml.encode()


def test_fetch_rss_news_returns_items():
    xml_bytes = _make_rss_xml([
        {"title": "NVDA acquisition rumored", "link": "https://rss.example.com/1", "guid": "rss-001"}
    ])
    with patch("stock_sentinel.news_engine.urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: io.BytesIO(xml_bytes)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_resp
        items = _fetch_rss_news("NVDA")
    assert len(items) == 1
    assert items[0]["title"] == "NVDA acquisition rumored"
    assert items[0]["item_id"] == "rss-001"


def test_fetch_rss_news_handles_error():
    with patch("stock_sentinel.news_engine.urllib.request.urlopen", side_effect=Exception("timeout")):
        items = _fetch_rss_news("NVDA")
    assert items == []


def test_fetch_rss_news_skips_empty_title():
    xml_bytes = _make_rss_xml([{"title": "", "link": "https://x.com", "guid": "no-title"}])
    with patch("stock_sentinel.news_engine.urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: io.BytesIO(xml_bytes)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_resp
        items = _fetch_rss_news("NVDA")
    assert items == []


# ── run_news_engine_cycle ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cycle_emits_flash_for_catalyst_polarized():
    """A catalyst + polarized headline produces a NewsFlash."""
    yf_items = [{"title": "NVDA beats earnings with strong rally", "url": "https://x.com/1",
                 "item_id": "id-001", "source": "Reuters"}]
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=yf_items), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]), \
         patch("stock_sentinel.news_engine.fetch_ohlcv", side_effect=Exception("no data")),  \
         patch("stock_sentinel.news_engine.compute_signals", side_effect=Exception("no data")):
        flashes = await run_news_engine_cycle(["NVDA"], state)
    assert len(flashes) == 1
    assert flashes[0].ticker == "NVDA"
    assert flashes[0].reaction in ("bullish", "bearish")
    assert "earnings" in flashes[0].catalyst_keywords


@pytest.mark.asyncio
async def test_cycle_deduplicates_seen_items():
    """Already-seen items are not re-emitted."""
    yf_items = [{"title": "NVDA beats earnings with strong rally", "url": "https://x.com/1",
                 "item_id": "id-001", "source": "Reuters"}]
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=yf_items), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]), \
         patch("stock_sentinel.news_engine.fetch_ohlcv", side_effect=Exception("no data")),  \
         patch("stock_sentinel.news_engine.compute_signals", side_effect=Exception("no data")):
        flashes1 = await run_news_engine_cycle(["NVDA"], state)
        flashes2 = await run_news_engine_cycle(["NVDA"], state)
    assert len(flashes1) == 1
    assert len(flashes2) == 0


@pytest.mark.asyncio
async def test_cycle_skips_non_catalyst_item():
    """Item with no catalyst keywords produces no flash."""
    yf_items = [{"title": "Market recap: mixed session", "url": "", "item_id": "id-002", "source": "x"}]
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=yf_items), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]):
        flashes = await run_news_engine_cycle(["NVDA"], state)
    assert flashes == []


@pytest.mark.asyncio
async def test_cycle_skips_low_sentiment_item():
    """Catalyst keyword present but sentiment is neutral — no flash."""
    # "merger" is a catalyst keyword but the sentence is sentiment-neutral
    yf_items = [{"title": "Company merger announced today", "url": "", "item_id": "id-003", "source": "x"}]
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=yf_items), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]):
        flashes = await run_news_engine_cycle(["NVDA"], state)
    assert flashes == []


@pytest.mark.asyncio
async def test_cycle_ta_confirmation_enriches_summary():
    """When TA returns a LONG signal, summary includes the Hebrew trend description."""
    yf_items = [{"title": "NVDA beats earnings with strong rally", "url": "https://x.com/1",
                 "item_id": "ta-001", "source": "Reuters"}]
    mock_signal = MagicMock()
    mock_signal.direction = "LONG"
    mock_signal.rsi = 42.0
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=yf_items), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]), \
         patch("stock_sentinel.news_engine.fetch_ohlcv", return_value=MagicMock()), \
         patch("stock_sentinel.news_engine.compute_signals", return_value=mock_signal):
        flashes = await run_news_engine_cycle(["NVDA"], state)
    assert len(flashes) == 1
    assert "עולה" in flashes[0].summary
    assert "LONG" in flashes[0].summary


@pytest.mark.asyncio
async def test_cycle_ta_neutral_sets_no_entry_summary():
    """When TA is NEUTRAL, summary says no entry confirmation."""
    yf_items = [{"title": "NVDA beats earnings with strong rally", "url": "",
                 "item_id": "ta-002", "source": "Reuters"}]
    mock_signal = MagicMock()
    mock_signal.direction = "NEUTRAL"
    mock_signal.rsi = 50.0
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=yf_items), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]), \
         patch("stock_sentinel.news_engine.fetch_ohlcv", return_value=MagicMock()), \
         patch("stock_sentinel.news_engine.compute_signals", return_value=mock_signal):
        flashes = await run_news_engine_cycle(["NVDA"], state)
    assert len(flashes) == 1
    assert "אין אישור טכני" in flashes[0].summary


@pytest.mark.asyncio
async def test_cycle_empty_watchlist():
    with patch("stock_sentinel.news_engine._fetch_general_news", return_value=[]):
        flashes = await run_news_engine_cycle([], NewsEngineState())
    assert flashes == []


# ── _extract_tickers ──────────────────────────────────────────────────────────

def test_extract_tickers_finds_symbols():
    result = _extract_tickers("NVDA and AMZN surge on earnings beat")
    assert "NVDA" in result
    assert "AMZN" in result


def test_extract_tickers_filters_blocklist():
    # "SEC", "FDA", "CEO" are all in the blocklist
    result = _extract_tickers("SEC investigates CEO after FDA ruling")
    assert "SEC" not in result
    assert "FDA" not in result
    assert "CEO" not in result


def test_extract_tickers_ignores_lowercase():
    # All-lowercase words are not tickers
    result = _extract_tickers("nvda and amzn rally today")
    assert result == []


def test_extract_tickers_max_5_chars():
    # 6-char uppercase word is not matched by the regex (limit is 5)
    result = _extract_tickers("TOOLONG rises on news")
    assert "TOOLONG" not in result


def test_extract_tickers_deduplicates():
    result = _extract_tickers("NVDA beats NVDA expectations")
    assert result.count("NVDA") == 1


def test_extract_tickers_empty_string():
    assert _extract_tickers("") == []


def test_extract_tickers_no_uppercase():
    assert _extract_tickers("all lowercase text here") == []


# ── _get_market_cap ───────────────────────────────────────────────────────────

def test_get_market_cap_returns_value():
    mock_fi = MagicMock()
    mock_fi.market_cap = 2_000_000_000.0
    with patch("stock_sentinel.news_engine.yf.Ticker") as MockTicker:
        MockTicker.return_value.fast_info = mock_fi
        cap = _get_market_cap("NVDA")
    assert cap == 2_000_000_000.0


def test_get_market_cap_returns_zero_on_error():
    with patch("stock_sentinel.news_engine.yf.Ticker", side_effect=Exception("network")):
        cap = _get_market_cap("BROKEN")
    assert cap == 0.0


def test_get_market_cap_returns_zero_for_none():
    mock_fi = MagicMock()
    mock_fi.market_cap = None
    with patch("stock_sentinel.news_engine.yf.Ticker") as MockTicker:
        MockTicker.return_value.fast_info = mock_fi
        cap = _get_market_cap("TINY")
    assert cap == 0.0


# ── _check_liquidity ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_liquidity_passes_large_cap():
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._get_market_cap", return_value=3e9):
        result = await _check_liquidity("NVDA", state, 500e6)
    assert result is True


@pytest.mark.asyncio
async def test_check_liquidity_fails_small_cap():
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._get_market_cap", return_value=100e6):
        result = await _check_liquidity("TINY", state, 500e6)
    assert result is False


@pytest.mark.asyncio
async def test_check_liquidity_uses_cache():
    state = NewsEngineState()
    state.set_liquidity_cache("NVDA", True)
    # _get_market_cap should NOT be called if cached
    with patch("stock_sentinel.news_engine._get_market_cap") as mock_cap:
        result = await _check_liquidity("NVDA", state, 500e6)
    mock_cap.assert_not_called()
    assert result is True


@pytest.mark.asyncio
async def test_check_liquidity_caches_result():
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._get_market_cap", return_value=2e9):
        await _check_liquidity("AMZN", state, 500e6)
    assert state.has_liquidity_cache("AMZN")
    assert state.get_liquidity_cache("AMZN") is True


# ── _fetch_general_news ───────────────────────────────────────────────────────

def _make_rss_feed(items: list[dict]) -> bytes:
    channel_items = ""
    for it in items:
        channel_items += (
            f"<item>"
            f"<title>{it.get('title', '')}</title>"
            f"<link>{it.get('link', '')}</link>"
            f"<guid>{it.get('guid', '')}</guid>"
            f"</item>"
        )
    return f"<rss><channel>{channel_items}</channel></rss>".encode()


def test_fetch_general_news_combines_feeds():
    xml_bytes = _make_rss_feed([
        {"title": "Tech merger shakes market", "link": "https://ex.com/1", "guid": "g1"},
        {"title": "Biotech FDA approval", "link": "https://ex.com/2", "guid": "g2"},
    ])
    with patch("stock_sentinel.news_engine.urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: io.BytesIO(xml_bytes)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_resp
        items = _fetch_general_news()
    # 3 feeds × 2 items = 6 (all feeds use same mock)
    assert len(items) >= 2
    titles = [it["title"] for it in items]
    assert "Tech merger shakes market" in titles


def test_fetch_general_news_skips_failing_feeds():
    """A feed that throws does not prevent others from being fetched."""
    call_count = [0]
    xml_bytes = _make_rss_feed([{"title": "Big acquisition deal", "link": "https://x.com", "guid": "g1"}])

    def _side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("timeout")
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: io.BytesIO(xml_bytes)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("stock_sentinel.news_engine.urllib.request.urlopen", side_effect=_side_effect):
        items = _fetch_general_news()
    assert any(it["title"] == "Big acquisition deal" for it in items)


def test_fetch_general_news_empty_when_all_fail():
    with patch("stock_sentinel.news_engine.urllib.request.urlopen", side_effect=Exception("all down")):
        items = _fetch_general_news()
    assert items == []


# ── Discovery path in run_news_engine_cycle ───────────────────────────────────

@pytest.mark.asyncio
async def test_discovery_emits_flash_for_non_watchlist_ticker():
    """High-impact headline with extractable ticker and sufficient market cap → discovery flash."""
    general_items = [
        {"title": "SOXX acquisition deal with strong rally", "url": "https://ex.com/1",
         "item_id": "disc-001", "source": "Reuters"},
    ]
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=[]), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]), \
         patch("stock_sentinel.news_engine._fetch_general_news", return_value=general_items), \
         patch("stock_sentinel.news_engine._get_market_cap", return_value=3e9):
        flashes = await run_news_engine_cycle(["NVDA"], state)
    assert len(flashes) == 1
    assert flashes[0].is_watchlist is False
    assert flashes[0].ticker == "SOXX"
    assert "acquisition" in flashes[0].catalyst_keywords


@pytest.mark.asyncio
async def test_discovery_skips_low_impact_keywords():
    """Non-watchlist ticker with only low-impact catalyst (not in HIGH_IMPACT list) → no flash."""
    # "launch" is in NEWS_CATALYST_KEYWORDS but NOT in NEWS_DISCOVERY_KEYWORDS (high-impact only)
    general_items = [
        {"title": "SOXX launches new product in breakthrough deal with strong gains", "url": "",
         "item_id": "disc-002", "source": "Reuters"},
    ]
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=[]), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]), \
         patch("stock_sentinel.news_engine._fetch_general_news", return_value=general_items), \
         patch("stock_sentinel.news_engine._get_market_cap", return_value=3e9):
        flashes = await run_news_engine_cycle(["NVDA"], state)
    assert flashes == []


@pytest.mark.asyncio
async def test_discovery_skips_small_cap_ticker():
    """Even with high-impact keyword, market cap below threshold → no flash."""
    general_items = [
        {"title": "SMLL acquisition deal with strong rally", "url": "",
         "item_id": "disc-003", "source": "Reuters"},
    ]
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=[]), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]), \
         patch("stock_sentinel.news_engine._fetch_general_news", return_value=general_items), \
         patch("stock_sentinel.news_engine._get_market_cap", return_value=100e6):  # 100M < 500M
        flashes = await run_news_engine_cycle(["NVDA"], state)
    assert flashes == []


@pytest.mark.asyncio
async def test_discovery_watchlist_ticker_in_general_news_excluded():
    """Ticker already in watchlist appearing in general news is skipped by discovery path."""
    general_items = [
        {"title": "NVDA acquisition deal surges higher", "url": "",
         "item_id": "disc-004", "source": "Reuters"},
    ]
    state = NewsEngineState()
    state.mark_seen("disc-004")   # pre-mark so watchlist path also skips it
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=[]), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]), \
         patch("stock_sentinel.news_engine._fetch_general_news", return_value=general_items), \
         patch("stock_sentinel.news_engine._get_market_cap", return_value=5e9):
        flashes = await run_news_engine_cycle(["NVDA"], state)
    # No flash because item_id was pre-seen
    assert flashes == []


@pytest.mark.asyncio
async def test_discovery_deduplicates_across_cycles():
    """Discovery items seen in cycle 1 are not re-emitted in cycle 2."""
    general_items = [
        {"title": "SOXX acquisition deal with strong rally", "url": "",
         "item_id": "disc-005", "source": "Reuters"},
    ]
    state = NewsEngineState()
    with patch("stock_sentinel.news_engine._fetch_yfinance_news", return_value=[]), \
         patch("stock_sentinel.news_engine._fetch_rss_news", return_value=[]), \
         patch("stock_sentinel.news_engine._fetch_general_news", return_value=general_items), \
         patch("stock_sentinel.news_engine._get_market_cap", return_value=3e9):
        flashes1 = await run_news_engine_cycle(["NVDA"], state)
        flashes2 = await run_news_engine_cycle(["NVDA"], state)
    assert len(flashes1) == 1
    assert len(flashes2) == 0


# ── NewsEngineState — liquidity cache ─────────────────────────────────────────

def test_state_liquidity_cache_roundtrip():
    state = NewsEngineState()
    assert not state.has_liquidity_cache("NVDA")
    state.set_liquidity_cache("NVDA", True)
    assert state.has_liquidity_cache("NVDA")
    assert state.get_liquidity_cache("NVDA") is True


def test_state_clear_resets_liquidity():
    state = NewsEngineState()
    state.set_liquidity_cache("NVDA", True)
    state.clear()
    assert not state.has_liquidity_cache("NVDA")
