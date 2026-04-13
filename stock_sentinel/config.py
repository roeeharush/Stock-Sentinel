import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

WATCHLIST = ["NVDA", "AMZN", "SOFI", "OKLO", "RKLB", "FLNC", "AXTI", "CIFR", "IREN", "UBER", "CRDO", "NBIS", "PL", "RKT", "ONDS", "OSS", "TSLA", "PANW"]
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

# Debate Engine settings
DEBATE_MODEL: str = "claude-haiku-4-5-20251001"   # fast + cheap for 3-agent debates
DEBATE_MAX_TOKENS: int = 400                        # per agent response

# Vision Agent settings
VISION_MODEL: str = "claude-sonnet-4-6"            # multimodal model for chart pattern analysis
VISION_MAX_TOKENS: int = 500                        # per Visionary response

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
X_COOKIES_PATH = str(_PROJECT_ROOT / "session" / "x_cookies.json")

SENTIMENT_MIN_TWEETS: int = 10
SENTIMENT_MIN_HEADLINES: int = 3
SENTIMENT_MIN_RSS_HEADLINES: int = 3
COOLDOWN_MINUTES = 120
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
ATR_SL_MULTIPLIER: float = 2.0    # updated: was 1.5 (wider stop for reliability)
ATR_TP_MULTIPLIER: float = 3.0    # backward-compat alias = TP2
ATR_TP1_MULTIPLIER: float = 1.5   # conservative target
ATR_TP2_MULTIPLIER: float = 3.0   # moderate target
ATR_TP3_MULTIPLIER: float = 5.0   # ambitious target
SCRAPER_CIRCUIT_BREAKER_N = 3
TECHNICAL_SCORE_MIN: int = 60        # minimum confluence score to trigger an alert
INSTITUTIONAL_SCORE_MIN: float = 2.0  # ⚠️  SMOKE TEST — restore to 6.0 for production
SMOKE_TEST_LIMIT: int = 3             # ⚠️  SMOKE TEST — max alerts per scanner cycle; set 0 to disable
VOLUME_SPIKE_MULTIPLIER: float = 2.0  # volume must exceed N× 20-period average
ADX_TREND_MIN: float = 25.0   # minimum ADX for "strong trend"
OBV_SLOPE_BARS: int = 5       # bars to measure OBV slope


# --- Calibration weights (adjust based on validator findings) ---
# Sentiment fusion weights (must sum to 1.0)
WEIGHT_RSS: float = 0.40
WEIGHT_NEWS: float = 0.40
WEIGHT_TWITTER: float = 0.20

# Technical confluence score weights (sum = 100)
SCORE_WEIGHT_EMA200: int = 25
SCORE_WEIGHT_PATTERN: int = 20
SCORE_WEIGHT_VOLUME: int = 20
SCORE_WEIGHT_RSI: int = 20
SCORE_WEIGHT_MACD: int = 15


# ── Task 19: News Catalyst Engine ─────────────────────────────────────────────
NEWS_ENGINE_POLL_MINUTES: int = 5          # how often to poll for breaking news
NEWS_SENTIMENT_THRESHOLD: float = 0.55    # |score| must exceed this to qualify as polarized
# Stricter keyword set for non-watchlist discovery (subset of catalyst keywords)
NEWS_DISCOVERY_KEYWORDS: list[str] = [
    "acquisition", "merger", "fda", "lawsuit", "sec", "earnings", "buyout", "partnership",
]
NEWS_DISCOVERY_MIN_MARKET_CAP: float = 500e6   # 500 M — minimum cap for discovered tickers

NEWS_CATALYST_KEYWORDS: list[str] = [
    # Corporate events
    "merger", "acquisition", "takeover", "buyout", "spinoff", "ipo",
    # Earnings / guidance
    "earnings", "revenue", "guidance", "beat", "miss", "outlook", "forecast",
    # Analyst actions
    "upgrade", "downgrade", "price target", "overweight", "underweight",
    # Regulatory / legal
    "fda", "approval", "lawsuit", "settlement", "sec", "investigation", "fine",
    # Dividends / buybacks
    "dividend", "buyback", "repurchase",
    # Product / innovation
    "breakthrough", "launch", "contract", "partnership", "deal",
    # Macro / crisis
    "bankruptcy", "default", "recall", "layoffs", "restructuring",
]

# ── Task 23: Global Macro & Political Catalyst Engine ─────────────────────────
MACRO_INFLUENCERS: list[str] = [
    "Trump", "Biden", "Powell", "Fed", "FOMC",
    "Interest Rates", "Interest Rate",
    "Tariff", "Trade War", "Inflation", "CPI", "Treasury",
]

# ── Task 17.2: Autonomous Hunter ──────────────────────────────────────────────
SCANNER_MIN_MARKET_CAP: float = 2e9     # 2 B minimum
SCANNER_MIN_VOLUME: int       = 1_000_000
SCANNER_TOP_N: int            = 25      # candidates fetched per scan cycle
SCANNER_COOLDOWN_HOURS: float = 4.0     # hours before same ticker can fire again
SCANNER_PRICE_MOVE_PCT: float = 3.0     # re-alert if price moved >3% since last alert
SCANNER_JITTER_MIN: float     = 5.0     # seconds — minimum random jitter between API calls
SCANNER_JITTER_MAX: float     = 10.0    # seconds — maximum random jitter
RR_MIN: float                 = 1.5     # minimum Risk/Reward ratio to pass filter
ATR_PCT_HIGH_THRESHOLD: float = 3.0     # ATR% >= this triggers SHORT_TERM via volatility


def validate_secrets() -> None:
    """Call from scheduler.main() before starting the loop."""
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
               if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


def debate_enabled() -> bool:
    """Return True when a real Anthropic API key is configured.

    Guards against the placeholder value left in .env so the engine doesn't
    attempt (and noisily fail) live API calls during development.
    """
    return bool(ANTHROPIC_API_KEY) and ANTHROPIC_API_KEY != "your-anthropic-api-key-here"
