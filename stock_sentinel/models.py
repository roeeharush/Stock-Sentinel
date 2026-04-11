from dataclasses import dataclass, field
from datetime import datetime, timezone
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
class NewsSentimentResult:
    ticker: str
    headlines: list[str]
    score: float          # -1.0 to +1.0
    headline_count: int
    fetched_at: datetime
    failed: bool = False

@dataclass
class RssSentimentResult:
    ticker: str
    headlines: list[str]
    score: float
    headline_count: int
    fetched_at: datetime
    failed: bool = False

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
    news_sentiment: NewsSentimentResult | None = None
    rss_sentiment: RssSentimentResult | None = None
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
    sentiment_score: float      # combined 40/40/20 weighted score
    twitter_score: float = 0.0  # raw twitter component (20%)
    news_score: float = 0.0     # raw yfinance news component (40%)
    rss_score: float = 0.0      # raw RSS component (40%)
    chart_path: str | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
