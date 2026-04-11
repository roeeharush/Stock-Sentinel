# Stock Sentinel

Automated US equity monitoring pipeline — scrapes X/Twitter & financial news sentiment, computes RSI/MA/ATR technical signals, and dispatches Telegram alerts with candlestick chart PNGs when both signals converge.

**Watchlist:** NVDA · AMZN · SOFI · OKLO · RKLB · FLNC · ANXI · AXTI

## Features

- **Technical Analysis** — RSI(14), SMA20/SMA50, ATR(14) via yfinance + pandas-ta. Computes Entry, Stop Loss (1.5× ATR), and Take Profit (3× ATR) levels.
- **Dual Sentiment Fusion** — Combines X/Twitter scraping (40% weight) and yfinance news headlines (60% weight) into a single convergence score. Alerts only fire when technical direction and combined sentiment agree.
- **Telegram Alerts** — Sends candlestick chart PNGs with full trade breakdown: direction, entry/SL/TP, RSI, individual sentiment scores, and top news headlines.
- **Resilient Scheduler** — APScheduler runs Mon–Fri 09:30–16:00 ET every 15 minutes. Per-ticker fault isolation ensures one failed ticker never stops the loop. Circuit breaker pauses the scraper and pings you after 3 consecutive failures.
- **2-Hour Cooldown** — Prevents alert spam by enforcing a per-ticker cooldown after each alert.

## Signal Logic

| Direction | Condition |
|---|---|
| **LONG** | RSI < 30 AND Close > SMA20 AND combined_sentiment > 0 |
| **SHORT** | RSI > 70 AND Close < SMA20 AND combined_sentiment < 0 |
| **No alert** | Technical and sentiment disagree, insufficient data, or cooldown active |

**Sentiment fusion:** `combined_score = 0.6 × news_score + 0.4 × twitter_score`

Graceful degradation: if one source fails, 100% weight falls on the available source. If both fail, no alert fires.

## Project Structure

```
stock_sentinel/
├── config.py          # Watchlist, thresholds, env-var loading
├── models.py          # Typed dataclasses (SentimentResult, TechnicalSignal, Alert, …)
├── scraper.py         # Playwright X/Twitter sentiment scraper
├── news_scraper.py    # yfinance news headlines sentiment
├── analyzer.py        # OHLCV fetch + RSI/SMA/ATR computation
├── signal_filter.py   # 60/40 sentiment fusion + convergence gate + cooldown
├── notifier.py        # mplfinance chart generation + Telegram dispatch
└── scheduler.py       # APScheduler orchestrator — main execution engine
tests/
├── test_models.py
├── test_analyzer.py
├── test_scraper.py
├── test_news_scraper.py
├── test_signal_filter.py
├── test_notifier.py
└── test_scheduler.py
run.py                 # Entry point
.env.example           # Credential template
requirements.txt       # Pinned dependencies
```

## Installation

**Prerequisites:** Python 3.11+, pip

**1. Clone and create a virtual environment**
```bash
git clone <repo-url>
cd stock-sentinel
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
playwright install chromium
```

**3. Configure credentials**
```bash
cp .env.example .env
```
Edit `.env` and set:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

To get your **bot token**: create a bot via [@BotFather](https://t.me/BotFather) on Telegram.

To get your **chat ID**: send any message to your bot, then open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` and look for `"chat":{"id":...}`.

## X/Twitter Session Cookies

The Twitter scraper uses Playwright with `playwright-stealth` to bypass bot detection, but it still requires a valid logged-in session to access search results. Without cookies, X will redirect to a login wall.

**How to generate `session/x_cookies.json`:**

**Option A — Export from browser (recommended)**

1. Log in to [x.com](https://x.com) in Chrome or Firefox.
2. Install the [Cookie-Editor](https://cookie-editor.com/) browser extension.
3. On x.com, open Cookie-Editor and click **Export → JSON**.
4. Create the `session/` directory and save the file:
   ```
   session/x_cookies.json
   ```

**Option B — Playwright interactive login**

Run this one-time script to log in manually and save the session:
```bash
python - <<'EOF'
import asyncio, json
from playwright.async_api import async_playwright

async def save_session():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://x.com/login")
        input("Log in manually, then press ENTER here to save cookies...")
        import os; os.makedirs("session", exist_ok=True)
        cookies = await context.cookies()
        with open("session/x_cookies.json", "w") as f:
            json.dump(cookies, f)
        print("Cookies saved to session/x_cookies.json")
        await browser.close()

asyncio.run(save_session())
EOF
```

The scheduler automatically refreshes `session/x_cookies.json` after each cycle to keep the session alive. The file is gitignored.

## Running the Bot

```bash
python run.py
```

The scheduler will start and log to stdout. It only fires during US market hours (Mon–Fri 09:30–16:00 ET). You can test the Telegram connection at any time — alerts are dispatched whenever signals converge, regardless of whether the market is open during manual testing.

**Stop the bot:** `Ctrl+C`

## Running Tests

```bash
python -m pytest tests/ -v
```

45 tests across 7 modules. All tests use mocks — no real Playwright browser, no live yfinance calls, no Telegram messages.
