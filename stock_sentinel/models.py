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
