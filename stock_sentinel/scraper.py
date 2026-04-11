import json
import os
from datetime import datetime, timezone
from typing import Any
from playwright.async_api import Browser, Page
from playwright_stealth import Stealth
from stock_sentinel.models import SentimentResult

BULLISH_TERMS = {"buy", "bullish", "long", "breakout", "upside", "calls", "rally", "dip"}
BEARISH_TERMS = {"sell", "bearish", "short", "dump", "downside", "puts", "crash"}
SHILL_BLOCKLIST = {"moon", "100x", "buy now", "gem", "lambo"}


def _score_texts(texts: list[str]) -> float:
    if not texts:
        return 0.0
    filtered = [t for t in texts if not any(s in t for s in SHILL_BLOCKLIST)]
    bull = sum(1 for t in filtered for w in BULLISH_TERMS if w in t)
    bear = sum(1 for t in filtered for w in BEARISH_TERMS if w in t)
    total = bull + bear
    return 0.0 if total == 0 else (bull - bear) / total


async def init_browser(cookies_path: str) -> tuple[Any, Browser, Page]:
    from playwright.async_api import async_playwright, Playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()
    await Stealth().apply_stealth_async(page)
    if os.path.exists(cookies_path):
        with open(cookies_path) as f:
            await context.add_cookies(json.load(f))
    return pw, browser, page


async def scrape_sentiment(ticker: str, page: Page) -> SentimentResult:
    url = f"https://x.com/search?q=%24{ticker}+lang%3Aen&src=typed_query&f=live"
    try:
        await page.goto(url, timeout=15000)
        await page.wait_for_selector('[data-testid="tweetText"]', timeout=10000)
        elements = await page.query_selector_all('[data-testid="tweetText"]')
        texts = [(await el.inner_text()).lower() for el in elements[:30]]
        return SentimentResult(
            ticker=ticker,
            score=_score_texts(texts),
            tweet_count=len(texts),
            scraped_at=datetime.now(timezone.utc),
        )
    except Exception:
        return SentimentResult(
            ticker=ticker,
            score=0.0,
            tweet_count=0,
            scraped_at=datetime.now(timezone.utc),
            failed=True,
        )


async def close_browser(pw: Any, browser: Browser) -> None:
    await browser.close()
    await pw.stop()


async def save_cookies(page: Page, cookies_path: str) -> None:
    os.makedirs(os.path.dirname(cookies_path) or ".", exist_ok=True)
    cookies = await page.context.cookies()
    with open(cookies_path, "w") as f:
        json.dump(cookies, f)
