# Stock Sentinel

> Automated trading intelligence — real-time technical analysis, multi-source sentiment fusion, and professional Hebrew alerts delivered directly to Telegram.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-124%20passing-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Overview

Stock Sentinel is a production-grade Python pipeline that monitors a configurable stock watchlist every 15 minutes during US market hours. For each ticker it runs a full technical and sentiment analysis pass, scores the confluence of signals, and fires a structured Telegram alert only when the evidence is strong enough to act on.

Sent alerts are tracked in a local SQLite database and monitored in real time — Telegram threads automatically when a take-profit or stop-loss level is hit.

---

## Key Features

### Technical Analysis Engine
- **RSI (14)** — oversold / overbought zone detection
- **SMA 20 / 50** — trend confirmation via moving-average relationship
- **EMA 200** — long-term trend bias (+25 pts to confluence score)
- **Bollinger Bands (20, 2σ)** — volatility breakout detection
- **MACD (12/26/9)** — momentum direction alignment
- **Stochastic RSI** — K/D crossover for short-term timing
- **ADX (14)** — trend strength filter (configurable threshold)
- **OBV** — volume accumulation / distribution slope
- **VWAP (rolling 20-bar)** — institutional price anchor
- **Candlestick patterns** — Bullish Engulfing, Hammer, Shooting Star (no TA-Lib dependency)
- **Volume Spike detector** — flags bars exceeding N× the 20-bar average volume
- **TechnicalScore (0–100)** — weighted confluence gate; alerts only fire when score ≥ 60

### Triple-Target ATR System

Every alert ships three price levels calculated from Average True Range:

| Target | Multiplier | Purpose |
|--------|-----------|---------|
| TP1    | 1.5 × ATR | Conservative — first profit lock |
| TP2    | 3.0 × ATR | Moderate — primary target |
| TP3    | 5.0 × ATR | Ambitious — full runner |
| SL     | 2.0 × ATR | Stop loss |

### Sentiment Analysis (40 / 40 / 20 Fusion)
- **RSS feeds (40%)** — aggregated financial news via `feedparser`
- **yfinance news (40%)** — company-specific headlines with keyword scoring
- **Twitter / X (20%)** — real-time crowd sentiment via Playwright (stealth, cookie-based)
- Proportional weight rebalancing when a source is unavailable

### Horizon Classifier

Each alert is labelled with a strategic trading horizon:

| Horizon | Trigger Conditions |
|---------|--------------------|
| `SHORT_TERM` | Volume spike OR BB breakout OR Stoch RSI crossover |
| `LONG_TERM`  | EMA 200 aligned AND ADX strong AND OBV rising |
| `BOTH`       | All short-term AND all long-term conditions met |

### Professional RTL Hebrew Telegram Alerts
- Full right-to-left Hebrew UI rendered in Telegram Markdown
- 40+ `TRADING_GLOSSARY` terms pre-substituted before machine translation (preserves financial accuracy)
- Candlestick chart attached to every alert (mplfinance, SMA20/50 overlays)
- Threaded trade updates — TP/SL hit notifications reply directly to the original alert message

### Real-time Trade Monitor
- Runs every 2 minutes during market hours via APScheduler
- Fetches live prices from yfinance `fast_info` (falls back to 1-minute bars)
- Fires TP1 → TP2 → TP3 updates sequentially; SL takes full priority over TPs
- All trade state persisted in SQLite — survives scheduler restarts

### Performance Tracking & Calibration
- Every alert logged to `data/sentinel.db` with full metadata
- Post-market validator (16:30 ET) resolves each alert as `WIN / LOSS / EXPIRED` by replaying OHLCV
- Daily performance report (17:00 ET) sent to Telegram: win rate, top confluence factors
- All scoring weights live in `config.py` — tune without touching logic

---

## Architecture

```
stock_sentinel/
├── config.py          # All tunable parameters and secrets loading
├── models.py          # Dataclasses: TechnicalSignal, Alert, TickerSnapshot, Sentiment*
├── analyzer.py        # Technical indicators → TechnicalSignal (pandas-ta)
├── scraper.py         # Playwright Twitter/X sentiment scraper
├── news_scraper.py    # yfinance headline sentiment
├── rss_provider.py    # RSS feed aggregation and scoring
├── signal_filter.py   # Confluence gate + combined_sentiment_score + cooldown
├── notifier.py        # Chart generation + Telegram send_alert / send_trade_update
├── translator.py      # Glossary pre-substitution + deep-translator Hebrew
├── monitor.py         # Real-time TP/SL price monitor
├── validator.py       # Post-market WIN/LOSS/EXPIRED resolver
├── db.py              # SQLite persistence layer (forward-compatible migrations)
└── scheduler.py       # APScheduler orchestrator — main execution engine
```

---

## Setup

### Prerequisites
- Python 3.11+
- A Telegram bot token and group/channel chat ID ([create one with @BotFather](https://t.me/BotFather))
- *(Optional)* Twitter/X session cookies for social sentiment

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/roeeharush/Stock-Sentinel.git
cd Stock-Sentinel
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_channel_or_group_chat_id
```

> The bot must be an **admin** in the target channel or group to send messages.

### 4. (Optional) Twitter/X Cookies

For live social sentiment, log into X in your browser, export cookies as JSON using the [Cookie-Editor](https://cookie-editor.com/) extension, and save to:

```
session/x_cookies.json
```

If the file is absent the Twitter component is skipped and weights are rebalanced to RSS + News automatically.

### 5. Customise the watchlist

Edit `WATCHLIST` in `stock_sentinel/config.py`:

```python
WATCHLIST = ["NVDA", "AMZN", "SOFI", "OKLO", "RKLB", "FLNC", "ANXI", "AXTI"]
```

### 6. Run

```bash
python run.py
```

The scheduler starts immediately. Monitoring cycles fire every 15 minutes at market hours (9:00–15:45 ET, Mon–Fri). Outside those hours APScheduler waits silently — no CPU spin.

---

## Tuning

All thresholds are constants in `stock_sentinel/config.py`:

| Constant | Default | Purpose |
|----------|---------|---------|
| `TECHNICAL_SCORE_MIN` | `60` | Minimum confluence score to fire an alert |
| `VOLUME_SPIKE_MULTIPLIER` | `2.0` | Volume must be N× the 20-bar average |
| `ADX_TREND_MIN` | `25.0` | ADX threshold for "strong trend" label |
| `ATR_TP1_MULTIPLIER` | `1.5` | Conservative take-profit distance |
| `ATR_TP2_MULTIPLIER` | `3.0` | Moderate take-profit distance |
| `ATR_TP3_MULTIPLIER` | `5.0` | Ambitious take-profit distance |
| `ATR_SL_MULTIPLIER` | `2.0` | Stop-loss distance |
| `WEIGHT_RSS` | `0.40` | RSS contribution to sentiment score |
| `WEIGHT_NEWS` | `0.40` | News contribution to sentiment score |
| `WEIGHT_TWITTER` | `0.20` | Twitter contribution to sentiment score |
| `COOLDOWN_MINUTES` | `120` | Minimum gap between alerts per ticker |

After enough trades are resolved by the validator, inspect `data/sentinel.db` to see which confluence factors correlate with the highest win rates and adjust weights accordingly.

---

## Running Tests

```bash
pytest -v
```

124 tests across all modules. No external network calls — all Telegram, yfinance, and Playwright interactions are mocked.

---

## Scheduler Jobs

| Job | Schedule | Purpose |
|-----|----------|---------|
| `run_cycle` | Every 15 min, 9:00–15:45 ET, Mon–Fri | Full analysis + alert cycle |
| `run_monitor` | Every 2 min, 9:00–15:45 ET, Mon–Fri | TP/SL live price monitor |
| `run_validation` | 16:30 ET, Mon–Fri | Post-market outcome validator |
| `run_daily_report` | 17:00 ET, Mon–Fri | Telegram performance report |

---

## Project Structure

```
.
├── stock_sentinel/        # Core package
├── tests/                 # Full test suite (124 tests)
├── docs/                  # Design specs and implementation plans
├── data/                  # SQLite database — git-ignored
├── session/               # X/Twitter cookies — git-ignored
├── run.py                 # Entrypoint
├── integration_test.py    # End-to-end Task 14 dry-run script
├── pyproject.toml
├── requirements.txt
└── .env.example
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
