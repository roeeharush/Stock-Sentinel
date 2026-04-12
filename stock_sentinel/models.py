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
    # --- New fields (Task 11) ---
    ema_200: float = 0.0
    vwap: float = 0.0
    volume_spike: bool = False
    candlestick_pattern: str = ""   # "Bullish Engulfing", "Hammer", "Shooting Star", or ""
    macd_bullish: bool = False       # True when MACD line > Signal line
    technical_score: int = 0         # 0-100 confluence score
    confluence_factors: list[str] = field(default_factory=list)
    # --- Task 13: Strategic Horizon ---
    take_profit_1: float = 0.0   # conservative  (1.5 × ATR)
    take_profit_3: float = 0.0   # ambitious     (5.0 × ATR)
    bb_breakout: bool = False        # price broke Bollinger Band aligned with direction
    stochrsi_crossover: bool = False # StochRSI K crossed above/below D
    adx_strong: bool = False         # ADX > ADX_TREND_MIN
    obv_rising: bool = False         # OBV positive slope over last N bars
    horizon: str = ""                # "SHORT_TERM", "LONG_TERM", "BOTH", or ""
    horizon_reason: str = ""         # Hebrew explanation sentence
    # --- Task 16: Expert Tier ---
    pivot_r1: float = 0.0            # Floor pivot resistance 1
    pivot_r2: float = 0.0            # Floor pivot resistance 2
    pivot_s1: float = 0.0            # Floor pivot support 1
    pivot_s2: float = 0.0            # Floor pivot support 2
    rsi_divergence: str = ""         # "bullish", "bearish", or ""
    poc_price: float = 0.0           # Volume Profile Point of Control
    golden_cross: bool = False       # SMA50 > EMA200 (current state)
    fib_618: float = 0.0             # Fibonacci 61.8% retracement level
    fib_65: float = 0.0              # Fibonacci 65.0% retracement level
    # --- Task 17.2: Hunter Engine ---
    ema_21: float = 0.0              # EMA 21 (short-term momentum line)
    ema_21_break: bool = False       # price crossed above/below EMA 21 aligned with direction
    atr_pct: float = 0.0             # ATR as % of close price
    risk_reward: float = 0.0         # (TP1 - entry) / (entry - SL), pre-computed

@dataclass
class ScannerCandidate:
    """A ticker surfaced by the autonomous market scanner."""
    ticker: str
    price: float
    change_pct: float        # % change on the day
    volume: int              # today's share volume
    market_cap: float        # approximate market cap in USD
    reason: str = ""         # "gainer" | "volume" | "52w_high"
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


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
    confluence_factors: list[str] = field(default_factory=list)
    take_profit_1: float = 0.0
    take_profit_3: float = 0.0
    horizon: str = ""
    horizon_reason: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # --- Task 16: Expert Tier ---
    institutional_score: float = 0.0  # 1-10 composite quality rating
    pct_sl: float = 0.0               # (stop_loss - entry) / entry * 100
    pct_tp1: float = 0.0
    pct_tp2: float = 0.0
    pct_tp3: float = 0.0
    vwap: float = 0.0
    poc_price: float = 0.0
    fib_618: float = 0.0
    golden_cross: bool = False
    rsi_divergence: str = ""
    pivot_r1: float = 0.0
    pivot_r2: float = 0.0
    pivot_s1: float = 0.0
    pivot_s2: float = 0.0
    # --- Task 17.2: Scanner ---
    scanner_hit: bool = False        # True when alert originated from market scanner
    risk_reward: float = 0.0         # (TP1 - entry) / (entry - SL)
    ema_21: float = 0.0              # EMA 21 value at signal time
