# Stock Sentinel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a modular Python pipeline that monitors US equity sentiment via X/Twitter scraping, computes RSI/MA/ATR technical signals, and dispatches Telegram alerts with chart PNGs when both signals converge.

**Architecture:** Three focused modules (scraper, analyzer, notifier) coordinated by APScheduler every 15 minutes during market hours. State flows through typed dataclasses. A signal filter gate (convergence + cooldown) prevents false-positive alerts. Circuit breaker disables scraper after 3 consecutive failures.

**Tech Stack:** Python 3.11+, Playwright + playwright-stealth, yfinance, pandas-ta, mplfinance, python-telegram-bot, APScheduler, pytest + pytest-asyncio

---

## File Structure

```
stock_sentinel/
├── config.py                  # Watchlist, thresholds, env-var loading
├── models.py                  # All shared dataclasses
├── scraper.py                 # Playwright X/Twitter sentiment scraper
├── analyzer.py                # yfinance OHLCV fetch + RSI/MA/ATR computation
├── signal_filter.py           # Convergence gate + per-ticker cooldown
├── notifier.py                # mplfinance chart generation + Telegram dispatch
├── scheduler.py               # APScheduler orchestrator — main entry point
└── session/
    └── x_cookies.json         # Persisted X login session (gitignored)
tests/
├── test_models.py
├── test_analyzer.py
├── test_scraper.py
├── test_signal_filter.py
└── test_notifier.py
docs/
└── superpowers/
    ├── specs/
    │   └── 2026-04-10-stock-sentinel-design.md
    └── plans/
        └── 2026-04-10-stock-sentinel.md
.env.example
.gitignore
requirements.txt
README.md
```

---

## Data Schema (`models.py`)

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

@dataclass
class SentimentResult:
    ticker: str
    score: float          # -1.0 (bearish) to +1.0 (bullish)
    tweet_count: int
    scraped_at: datetime
    source: str = "x"
    failed: bool = False  # True if Playwright was blocked

@dataclass
class TechnicalSignal:
    ticker: str
    rsi: float
    ma_20: float
    ma_50: float
    atr: float
    entry: float
    stop_loss: float
    take_profit: float
    direction: Literal["LONG", "SHORT", "NEUTRAL"]
    analyzed_at: datetime

@dataclass
class TickerSnapshot:
    ticker: str
    sentiment: SentimentResult | None = None
    technical: TechnicalSignal | None = None
    last_alert_at: datetime | None = None

@dataclass
class Alert:
    ticker: str
    direction: Literal["LONG", "SHORT"]
    entry: float
    stop_loss: float
    take_profit: float
    rsi: float
    sentiment_score: float
    chart_path: str | None
    generated_at: datetime
```

---

## Module API Signatures

### `config.py`
```python
WATCHLIST: list[str]            # ["NVDA", "AMZN", "SOFI", "OKLO", "RKLB", "FLNC", "ANXI", "AXTI"]
TELEGRAM_BOT_TOKEN: str         # from .env
TELEGRAM_CHAT_ID: str           # from .env
X_COOKIES_PATH: str             # "session/x_cookies.json"
SENTIMENT_MIN_TWEETS: int       # 10
COOLDOWN_MINUTES: int           # 120
RSI_OVERSOLD: float             # 30.0
RSI_OVERBOUGHT: float           # 70.0
ATR_SL_MULTIPLIER: float        # 1.5
ATR_TP_MULTIPLIER: float        # 3.0
SCRAPER_CIRCUIT_BREAKER_N: int  # 3
```

### `analyzer.py`
```python
def fetch_ohlcv(ticker: str, period: str = "60d", interval: str = "1d") -> pd.DataFrame: ...
def compute_signals(ticker: str, df: pd.DataFrame) -> TechnicalSignal: ...
```

### `scraper.py`
```python
async def init_browser(cookies_path: str) -> tuple[Browser, Page]: ...
async def scrape_sentiment(ticker: str, page: Page) -> SentimentResult: ...
async def close_browser(browser: Browser) -> None: ...
def save_cookies(page: Page, cookies_path: str) -> None: ...
def _score_texts(texts: list[str]) -> float: ...
```

### `signal_filter.py`
```python
def should_alert(snapshot: TickerSnapshot) -> bool: ...
def update_cooldown(snapshot: TickerSnapshot) -> TickerSnapshot: ...
```

### `notifier.py`
```python
def generate_chart(ticker: str, df: pd.DataFrame, signal: TechnicalSignal) -> str: ...
def build_message(alert: Alert) -> str: ...
async def send_alert(alert: Alert, bot_token: str, chat_id: str) -> bool: ...
```

### `scheduler.py`
```python
def run_cycle(state: dict[str, TickerSnapshot]) -> None: ...
async def _async_cycle(state: dict[str, TickerSnapshot]) -> None: ...
def main() -> None: ...
```

---

## Tasks

### Task 1: Project Scaffold

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `requirements.txt`
- Create: `stock_sentinel/__init__.py`

- [ ] **Step 1: Create `.gitignore`**

```
venv/
.env
session/x_cookies.json
/tmp/stock_sentinel_*.png
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 2: Create `.env.example`**

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

- [ ] **Step 3: Create `requirements.txt`**

```
playwright==1.44.0
playwright-stealth==1.0.6
yfinance==0.2.38
pandas==2.2.2
pandas-ta==0.3.14b
mplfinance==0.12.10b0
matplotlib==3.9.0
python-telegram-bot==21.3
APScheduler==3.10.4
python-dotenv==1.0.1
pytest==8.2.2
pytest-asyncio==0.23.7
```

- [ ] **Step 4: Create empty `stock_sentinel/__init__.py` and `tests/__init__.py`**

- [ ] **Step 5: Commit**

```bash
git init
git add .gitignore .env.example requirements.txt stock_sentinel/__init__.py tests/__init__.py
git commit -m "chore: scaffold project structure and dependencies"
```

---

### Task 2: Config + Data Models

**Files:**
- Create: `stock_sentinel/config.py`
- Create: `stock_sentinel/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing test `tests/test_models.py`**

```python
from datetime import datetime
from stock_sentinel.models import SentimentResult, TechnicalSignal, TickerSnapshot, Alert

def test_sentiment_result_defaults():
    s = SentimentResult(ticker="NVDA", score=0.5, tweet_count=15, scraped_at=datetime.utcnow())
    assert s.failed is False
    assert s.source == "x"

def test_technical_signal_fields():
    t = TechnicalSignal(
        ticker="NVDA", rsi=28.0, ma_20=800.0, ma_50=780.0, atr=12.5,
        entry=810.0, stop_loss=791.25, take_profit=847.5,
        direction="LONG", analyzed_at=datetime.utcnow()
    )
    assert t.direction == "LONG"

def test_ticker_snapshot_defaults():
    snap = TickerSnapshot(ticker="AMZN")
    assert snap.sentiment is None
    assert snap.last_alert_at is None
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_models.py -v
```
Expected: FAIL with ImportError

- [ ] **Step 3: Create `stock_sentinel/models.py`** (full schema from Data Schema section above)

- [ ] **Step 4: Create `stock_sentinel/config.py`**

```python
import os
from dotenv import load_dotenv

load_dotenv()

WATCHLIST = ["NVDA", "AMZN", "SOFI", "OKLO", "RKLB", "FLNC", "ANXI", "AXTI"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
X_COOKIES_PATH = "session/x_cookies.json"
SENTIMENT_MIN_TWEETS = 10
COOLDOWN_MINUTES = 120
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
ATR_SL_MULTIPLIER = 1.5
ATR_TP_MULTIPLIER = 3.0
SCRAPER_CIRCUIT_BREAKER_N = 3
```

- [ ] **Step 5: Run to verify pass**

```
pytest tests/test_models.py -v
```
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add stock_sentinel/config.py stock_sentinel/models.py tests/test_models.py
git commit -m "feat(models): add dataclasses and env-based config"
```

---

### Task 3: Analyzer Module

**Files:**
- Create: `stock_sentinel/analyzer.py`
- Test: `tests/test_analyzer.py`

- [ ] **Step 1: Write failing test `tests/test_analyzer.py`**

```python
import pandas as pd
import numpy as np
import pytest
from unittest.mock import patch
from datetime import datetime
from stock_sentinel.analyzer import fetch_ohlcv, compute_signals
from stock_sentinel.models import TechnicalSignal

def _mock_df():
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(60))
    return pd.DataFrame({
        "Open": close - 0.5, "High": close + 1.0,
        "Low": close - 1.0, "Close": close,
        "Volume": np.random.randint(1_000_000, 5_000_000, 60)
    }, index=pd.date_range("2025-01-01", periods=60, freq="B"))

def test_compute_signals_returns_technical_signal():
    df = _mock_df()
    result = compute_signals("NVDA", df)
    assert isinstance(result, TechnicalSignal)
    assert result.ticker == "NVDA"
    assert 0 < result.rsi < 100
    assert result.atr > 0
    assert result.direction in ("LONG", "SHORT", "NEUTRAL")

def test_compute_signals_long_sl_below_entry():
    df = _mock_df()
    df["RSI_14"] = 25.0
    result = compute_signals("NVDA", df)
    if result.direction == "LONG":
        assert result.stop_loss < result.entry
        assert result.take_profit > result.entry

def test_fetch_ohlcv_raises_on_empty():
    with patch("yfinance.download", return_value=pd.DataFrame()):
        with pytest.raises(ValueError, match="No OHLCV data"):
            fetch_ohlcv("FAKE")
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_analyzer.py -v
```
Expected: FAIL with ImportError

- [ ] **Step 3: Create `stock_sentinel/analyzer.py`**

```python
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime
from stock_sentinel.models import TechnicalSignal
from stock_sentinel.config import RSI_OVERSOLD, RSI_OVERBOUGHT, ATR_SL_MULTIPLIER, ATR_TP_MULTIPLIER

def fetch_ohlcv(ticker: str, period: str = "60d", interval: str = "1d") -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        raise ValueError(f"No OHLCV data returned for {ticker}")
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df

def compute_signals(ticker: str, df: pd.DataFrame) -> TechnicalSignal:
    df = df.copy()
    if "RSI_14" not in df.columns:
        df.ta.rsi(length=14, append=True)
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.atr(length=14, append=True)

    latest = df.iloc[-1]
    rsi   = float(latest.get("RSI_14", 50.0))
    ma_20 = float(latest.get("SMA_20", latest["Close"]))
    ma_50 = float(latest.get("SMA_50", latest["Close"]))
    atr   = float(latest.get("ATRr_14", latest["Close"] * 0.01))
    close = float(latest["Close"])

    if rsi < RSI_OVERSOLD and close > ma_20:
        direction = "LONG"
    elif rsi > RSI_OVERBOUGHT and close < ma_20:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    if direction == "LONG":
        stop_loss   = close - ATR_SL_MULTIPLIER * atr
        take_profit = close + ATR_TP_MULTIPLIER * atr
    elif direction == "SHORT":
        stop_loss   = close + ATR_SL_MULTIPLIER * atr
        take_profit = close - ATR_TP_MULTIPLIER * atr
    else:
        stop_loss   = close - atr
        take_profit = close + atr

    return TechnicalSignal(
        ticker=ticker, rsi=rsi, ma_20=ma_20, ma_50=ma_50, atr=atr,
        entry=close, stop_loss=stop_loss, take_profit=take_profit,
        direction=direction, analyzed_at=datetime.utcnow()
    )
```

- [ ] **Step 4: Run to verify pass**

```
pytest tests/test_analyzer.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add stock_sentinel/analyzer.py tests/test_analyzer.py
git commit -m "feat(analyzer): add OHLCV fetch and RSI/MA/ATR signal computation"
```

---

### Task 4: Scraper Module

**Files:**
- Create: `stock_sentinel/scraper.py`
- Test: `tests/test_scraper.py`

- [ ] **Step 1: Write failing test `tests/test_scraper.py`**

```python
import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from stock_sentinel.scraper import scrape_sentiment, _score_texts
from stock_sentinel.models import SentimentResult

def test_score_texts_bullish():
    assert _score_texts(["nvda breakout bullish calls", "buy the dip rally"]) > 0.0

def test_score_texts_bearish():
    assert _score_texts(["nvda dump puts crash", "sell short bearish"]) < 0.0

def test_score_texts_empty_returns_zero():
    assert _score_texts([]) == 0.0

@pytest.mark.asyncio
async def test_scrape_sentiment_failed_on_exception():
    mock_page = AsyncMock()
    mock_page.goto.side_effect = Exception("timeout")
    result = await scrape_sentiment("NVDA", mock_page)
    assert isinstance(result, SentimentResult)
    assert result.failed is True
    assert result.ticker == "NVDA"

@pytest.mark.asyncio
async def test_scrape_sentiment_low_count_not_failed():
    mock_page = AsyncMock()
    mock_tweet = AsyncMock()
    mock_tweet.inner_text = AsyncMock(return_value="bullish nvda")
    mock_page.query_selector_all = AsyncMock(return_value=[mock_tweet] * 5)
    result = await scrape_sentiment("NVDA", mock_page)
    assert result.failed is False
    assert result.tweet_count == 5
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_scraper.py -v
```
Expected: FAIL with ImportError

- [ ] **Step 3: Create `stock_sentinel/scraper.py`**

```python
import json
import os
from datetime import datetime
from playwright.async_api import async_playwright, Browser, Page
from playwright_stealth import stealth_async
from stock_sentinel.models import SentimentResult

BULLISH_TERMS = {"buy", "bullish", "long", "breakout", "upside", "calls", "rally"}
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

async def init_browser(cookies_path: str) -> tuple[Browser, Page]:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    await stealth_async(page)
    if os.path.exists(cookies_path):
        with open(cookies_path) as f:
            await page.context.add_cookies(json.load(f))
    return browser, page

async def scrape_sentiment(ticker: str, page: Page) -> SentimentResult:
    url = f"https://x.com/search?q=%24{ticker}+lang%3Aen&src=typed_query&f=live"
    try:
        await page.goto(url, timeout=15000)
        await page.wait_for_selector('[data-testid="tweetText"]', timeout=10000)
        elements = await page.query_selector_all('[data-testid="tweetText"]')
        texts = [(await el.inner_text()).lower() for el in elements[:30]]
        return SentimentResult(
            ticker=ticker, score=_score_texts(texts),
            tweet_count=len(texts), scraped_at=datetime.utcnow()
        )
    except Exception:
        return SentimentResult(
            ticker=ticker, score=0.0,
            tweet_count=0, scraped_at=datetime.utcnow(), failed=True
        )

async def close_browser(browser: Browser) -> None:
    await browser.close()

def save_cookies(page: Page, cookies_path: str) -> None:
    os.makedirs(os.path.dirname(cookies_path), exist_ok=True)
    cookies = page.context.cookies()
    with open(cookies_path, "w") as f:
        json.dump(cookies, f)
```

- [ ] **Step 4: Run to verify pass**

```
pytest tests/test_scraper.py -v
```
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add stock_sentinel/scraper.py tests/test_scraper.py
git commit -m "feat(scraper): add Playwright X sentiment scraper with cookie session support"
```

---

### Task 5: Signal Filter

**Files:**
- Create: `stock_sentinel/signal_filter.py`
- Test: `tests/test_signal_filter.py`

- [ ] **Step 1: Write failing test `tests/test_signal_filter.py`**

```python
from datetime import datetime, timedelta
from stock_sentinel.models import TickerSnapshot, SentimentResult, TechnicalSignal
from stock_sentinel.signal_filter import should_alert, update_cooldown

def _snap(direction="LONG", score=0.6, tweet_count=15,
          failed=False, last_alert_minutes_ago=None):
    now = datetime.utcnow()
    return TickerSnapshot(
        ticker="NVDA",
        sentiment=SentimentResult(
            ticker="NVDA", score=score, tweet_count=tweet_count,
            scraped_at=now, failed=failed
        ),
        technical=TechnicalSignal(
            ticker="NVDA", rsi=25.0, ma_20=800.0, ma_50=780.0, atr=12.0,
            entry=810.0, stop_loss=792.0, take_profit=846.0,
            direction=direction, analyzed_at=now
        ),
        last_alert_at=(now - timedelta(minutes=last_alert_minutes_ago)
                       if last_alert_minutes_ago else None)
    )

def test_valid_long_alerts():
    assert should_alert(_snap()) is True

def test_failed_scraper_no_alert():
    assert should_alert(_snap(failed=True)) is False

def test_low_tweet_count_no_alert():
    assert should_alert(_snap(tweet_count=5)) is False

def test_neutral_direction_no_alert():
    assert should_alert(_snap(direction="NEUTRAL")) is False

def test_sentiment_disagrees_no_alert():
    assert should_alert(_snap(direction="LONG", score=-0.4)) is False

def test_cooldown_active_no_alert():
    assert should_alert(_snap(last_alert_minutes_ago=30)) is False

def test_cooldown_expired_alerts():
    assert should_alert(_snap(last_alert_minutes_ago=130)) is True

def test_update_cooldown_stamps_now():
    snap = _snap()
    updated = update_cooldown(snap)
    assert updated.last_alert_at is not None
    assert (datetime.utcnow() - updated.last_alert_at).seconds < 2
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_signal_filter.py -v
```
Expected: FAIL with ImportError

- [ ] **Step 3: Create `stock_sentinel/signal_filter.py`**

```python
from datetime import datetime, timedelta
from stock_sentinel.models import TickerSnapshot
from stock_sentinel.config import SENTIMENT_MIN_TWEETS, COOLDOWN_MINUTES

def should_alert(snapshot: TickerSnapshot) -> bool:
    s = snapshot.sentiment
    t = snapshot.technical
    if s is None or t is None:
        return False
    if s.failed:
        return False
    if s.tweet_count < SENTIMENT_MIN_TWEETS:
        return False
    if t.direction == "NEUTRAL":
        return False
    if t.direction == "LONG" and s.score <= 0:
        return False
    if t.direction == "SHORT" and s.score >= 0:
        return False
    if snapshot.last_alert_at is not None:
        if datetime.utcnow() - snapshot.last_alert_at < timedelta(minutes=COOLDOWN_MINUTES):
            return False
    return True

def update_cooldown(snapshot: TickerSnapshot) -> TickerSnapshot:
    snapshot.last_alert_at = datetime.utcnow()
    return snapshot
```

- [ ] **Step 4: Run to verify pass**

```
pytest tests/test_signal_filter.py -v
```
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add stock_sentinel/signal_filter.py tests/test_signal_filter.py
git commit -m "feat(filter): add convergence gate and per-ticker cooldown"
```

---

### Task 6: Notifier Module

**Files:**
- Create: `stock_sentinel/notifier.py`
- Test: `tests/test_notifier.py`

- [ ] **Step 1: Write failing test `tests/test_notifier.py`**

```python
import os
import numpy as np
import pandas as pd
import pytest
from datetime import datetime
from stock_sentinel.notifier import build_message, generate_chart
from stock_sentinel.models import Alert, TechnicalSignal

def _signal():
    return TechnicalSignal(
        ticker="NVDA", rsi=27.0, ma_20=800.0, ma_50=780.0, atr=12.0,
        entry=810.0, stop_loss=792.0, take_profit=846.0,
        direction="LONG", analyzed_at=datetime.utcnow()
    )

def _df():
    np.random.seed(1)
    close = 800 + np.cumsum(np.random.randn(60))
    return pd.DataFrame({
        "Open": close - 0.5, "High": close + 1.0,
        "Low": close - 1.0, "Close": close,
        "Volume": np.random.randint(1_000_000, 5_000_000, 60)
    }, index=pd.date_range("2025-01-01", periods=60, freq="B"))

def _alert():
    return Alert(
        ticker="NVDA", direction="LONG", entry=810.0,
        stop_loss=792.0, take_profit=846.0, rsi=27.0,
        sentiment_score=0.6, chart_path=None, generated_at=datetime.utcnow()
    )

def test_build_message_contains_required_fields():
    msg = build_message(_alert())
    for fragment in ["NVDA", "LONG", "810", "792", "846", "RSI"]:
        assert fragment in msg

def test_generate_chart_creates_png():
    path = generate_chart("NVDA", _df(), _signal())
    assert os.path.exists(path)
    assert path.endswith(".png")
    os.remove(path)
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_notifier.py -v
```
Expected: FAIL with ImportError

- [ ] **Step 3: Create `stock_sentinel/notifier.py`**

```python
import os
import tempfile
import asyncio
import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf
import pandas as pd
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError
from stock_sentinel.models import Alert, TechnicalSignal

def build_message(alert: Alert) -> str:
    return (
        f"[Stock Sentinel] {alert.ticker} — {alert.direction}\n"
        f"Entry:     ${alert.entry:.2f}\n"
        f"SL:        ${alert.stop_loss:.2f}\n"
        f"TP:        ${alert.take_profit:.2f}\n"
        f"RSI:       {alert.rsi:.1f}\n"
        f"Sentiment: {alert.sentiment_score:+.2f}\n"
        f"Generated: {alert.generated_at.strftime('%Y-%m-%d %H:%M')} UTC"
    )

def generate_chart(ticker: str, df: pd.DataFrame, signal: TechnicalSignal) -> str:
    df = df.copy().tail(30)
    ma20 = df["Close"].rolling(20).mean()
    ma50 = df["Close"].rolling(50).mean()
    adds = [
        mpf.make_addplot(ma20, color="blue", width=1.2),
        mpf.make_addplot(ma50, color="orange", width=1.2),
    ]
    path = os.path.join(tempfile.gettempdir(), f"stock_sentinel_{ticker}.png")
    mpf.plot(
        df, type="candle", style="charles", addplot=adds,
        title=f"{ticker} | RSI:{signal.rsi:.1f} | {signal.direction}",
        savefig=dict(fname=path, dpi=150, bbox_inches="tight"),
        figsize=(10, 6)
    )
    return path

async def send_alert(alert: Alert, bot_token: str, chat_id: str) -> bool:
    bot = Bot(token=bot_token)
    text = build_message(alert)
    for attempt in range(3):
        try:
            if alert.chart_path and os.path.exists(alert.chart_path):
                with open(alert.chart_path, "rb") as photo:
                    await bot.send_photo(chat_id=chat_id, photo=photo, caption=text)
            else:
                await bot.send_message(chat_id=chat_id, text=text)
            return True
        except TelegramError:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt * 2)
    return False
```

- [ ] **Step 4: Run to verify pass**

```
pytest tests/test_notifier.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add stock_sentinel/notifier.py tests/test_notifier.py
git commit -m "feat(notifier): add mplfinance chart generation and Telegram dispatch"
```

---

### Task 7: Scheduler / Orchestrator

**Files:**
- Create: `stock_sentinel/scheduler.py`

- [ ] **Step 1: Create `stock_sentinel/scheduler.py`**

```python
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from stock_sentinel import config
from stock_sentinel.models import TickerSnapshot, Alert
from stock_sentinel.analyzer import fetch_ohlcv, compute_signals
from stock_sentinel.scraper import init_browser, scrape_sentiment, close_browser, save_cookies
from stock_sentinel.signal_filter import should_alert, update_cooldown
from stock_sentinel.notifier import generate_chart, send_alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_scrape_fail_count = 0

def run_cycle(state: dict[str, TickerSnapshot]) -> None:
    asyncio.run(_async_cycle(state))

async def _async_cycle(state: dict[str, TickerSnapshot]) -> None:
    global _scrape_fail_count
    browser, page = await init_browser(config.X_COOKIES_PATH)
    try:
        for ticker in config.WATCHLIST:
            snap = state.setdefault(ticker, TickerSnapshot(ticker=ticker))

            sentiment = await scrape_sentiment(ticker, page)
            snap.sentiment = sentiment

            if sentiment.failed:
                _scrape_fail_count += 1
                log.warning(f"{ticker}: scrape failed ({_scrape_fail_count} consecutive)")
            else:
                _scrape_fail_count = 0

            if _scrape_fail_count >= config.SCRAPER_CIRCUIT_BREAKER_N:
                log.error("Circuit breaker triggered: scraper paused for this cycle")
                await send_alert(
                    Alert(
                        ticker="SYSTEM", direction="LONG", entry=0, stop_loss=0,
                        take_profit=0, rsi=0, sentiment_score=0,
                        chart_path=None, generated_at=datetime.utcnow()
                    ),
                    config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
                )
                break

            try:
                df = fetch_ohlcv(ticker)
                snap.technical = compute_signals(ticker, df)
            except ValueError as e:
                log.warning(f"{ticker}: {e}")
                continue

            if should_alert(snap):
                chart_path = generate_chart(ticker, df, snap.technical)
                alert = Alert(
                    ticker=ticker,
                    direction=snap.technical.direction,
                    entry=snap.technical.entry,
                    stop_loss=snap.technical.stop_loss,
                    take_profit=snap.technical.take_profit,
                    rsi=snap.technical.rsi,
                    sentiment_score=snap.sentiment.score,
                    chart_path=chart_path,
                    generated_at=datetime.utcnow()
                )
                success = await send_alert(alert, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
                if success:
                    state[ticker] = update_cooldown(snap)
                    log.info(f"Alert sent: {ticker} {snap.technical.direction}")
    finally:
        save_cookies(page, config.X_COOKIES_PATH)
        await close_browser(browser)

def main() -> None:
    state: dict[str, TickerSnapshot] = {}
    scheduler = BlockingScheduler(timezone="America/New_York")
    scheduler.add_job(
        run_cycle,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="0,15,30,45",
                    timezone="America/New_York"),
        args=[state]
    )
    log.info("Stock Sentinel started. Watching: " + ", ".join(config.WATCHLIST))
    scheduler.start()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run full suite**

```
pytest tests/ -v
```
Expected: All tests PASSED

- [ ] **Step 3: Commit**

```bash
git add stock_sentinel/scheduler.py
git commit -m "feat(scheduler): add APScheduler orchestrator with circuit breaker"
```

---

### Task 8: README + Final Verification

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create `README.md`**

```markdown
# Stock Sentinel

US equity monitoring pipeline: Playwright X/Twitter sentiment + RSI/MA/ATR technical analysis → Telegram alerts with chart PNGs.

**Watchlist:** NVDA, AMZN, SOFI, OKLO, RKLB, FLNC, ANXI, AXTI

## Setup

1. `pip install -r requirements.txt`
2. `playwright install chromium`
3. `cp .env.example .env` and fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
4. *(Optional)* Save X session cookies to `session/x_cookies.json`
5. `python -m stock_sentinel.scheduler`

## Architecture

```
APScheduler (15 min, market hours)
  └── scraper.py     → SentimentResult per ticker
  └── analyzer.py    → TechnicalSignal (RSI/MA20/MA50/ATR + Entry/SL/TP)
  └── signal_filter  → Convergence gate + cooldown
  └── notifier.py    → mplfinance PNG + Telegram dispatch
```

## Signal Logic

- **LONG**: RSI < 30, Close > SMA20, sentiment score > 0
- **SHORT**: RSI > 70, Close < SMA20, sentiment score < 0
- No alert fires unless both technical and sentiment agree
- 2-hour cooldown per ticker after an alert
```

- [ ] **Step 2: Final test run**

```
pytest tests/ -v
```
Expected: All 18+ tests PASSED, 0 failed

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and architecture overview"
```

---

## GitHub Commit Structure

| # | Commit Message | What ships |
|---|---|---|
| 1 | `chore: scaffold project structure and dependencies` | .gitignore, requirements.txt, .env.example |
| 2 | `feat(models): add dataclasses and env-based config` | models.py, config.py, test_models.py |
| 3 | `feat(analyzer): add OHLCV fetch and RSI/MA/ATR signal computation` | analyzer.py, test_analyzer.py |
| 4 | `feat(scraper): add Playwright X sentiment scraper with cookie session support` | scraper.py, test_scraper.py |
| 5 | `feat(filter): add convergence gate and per-ticker cooldown` | signal_filter.py, test_signal_filter.py |
| 6 | `feat(notifier): add mplfinance chart generation and Telegram dispatch` | notifier.py, test_notifier.py |
| 7 | `feat(scheduler): add APScheduler orchestrator with circuit breaker` | scheduler.py |
| 8 | `docs: add README with setup and architecture overview` | README.md |
