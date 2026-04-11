import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

WATCHLIST = ["NVDA", "AMZN", "SOFI", "OKLO", "RKLB", "FLNC", "ANXI", "AXTI"]
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
X_COOKIES_PATH = str(_PROJECT_ROOT / "session" / "x_cookies.json")

SENTIMENT_MIN_TWEETS: int = 10
SENTIMENT_MIN_HEADLINES: int = 3
SENTIMENT_MIN_RSS_HEADLINES: int = 3
COOLDOWN_MINUTES = 120
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
ATR_SL_MULTIPLIER = 1.5
ATR_TP_MULTIPLIER = 3.0
SCRAPER_CIRCUIT_BREAKER_N = 3


def validate_secrets() -> None:
    """Call from scheduler.main() before starting the loop."""
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
               if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
