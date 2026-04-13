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
class NewsFlash:
    """A single high-impact news item surfaced by the News Catalyst Engine."""
    ticker: str
    title: str                  # original headline
    summary: str                # 1-2 sentence summary (may equal title if no body)
    url: str                    # direct link to the article
    source: str                 # publisher / feed name
    sentiment_score: float      # -1.0 to +1.0
    catalyst_keywords: list[str] = field(default_factory=list)  # matched keywords
    reaction: str = ""          # "bullish" | "bearish"
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    item_id: str = ""           # de-duplication key (url or guid)
    is_watchlist: bool = True   # False → discovered via general news scan


@dataclass
class MacroFlash:
    """A high-impact macro / political headline with no specific ticker."""
    title: str
    summary: str                # 1-2 sentence market-impact explanation
    url: str
    source: str
    sentiment_score: float      # -1.0 to +1.0
    influencers: list[str] = field(default_factory=list)   # matched MACRO_INFLUENCERS
    reaction: str = ""          # "bullish" (risk-on) | "bearish" (risk-off)
    affected_assets: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "DIA"])
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    item_id: str = ""


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
class PatternFinding:
    """A single failure pattern identified by the Learning Engine."""
    pattern_type: str        # "rsi_ceiling" | "ticker_block" | "day_block" | "hour_block"
    description_heb: str     # human-readable Hebrew description
    failure_rate: float      # 0.0 to 1.0
    sample_count: int
    failed_count: int
    action_heb: str          # what was done (Hebrew)
    # Blacklist action fields (one populated per type)
    rsi_ceiling: float | None = None     # set for "rsi_ceiling"
    blocked_ticker: str | None = None    # set for "ticker_block"
    blocked_day: int | None = None       # set for "day_block"  (weekday() 0=Mon)
    blocked_hour: int | None = None      # set for "hour_block" (ET hour)


@dataclass
class LearningReport:
    """Output of one weekly Self-Learning Engine run."""
    analysis_date: datetime
    week_start: datetime
    week_end: datetime
    total_trades: int          # resolved trades analysed
    wins: int
    losses: int
    unresolved: int            # trades still open (not counted in win rate)
    win_rate_before: float     # raw win rate this week
    win_rate_after: float      # projected win rate after filters applied
    trades_filtered: int       # how many trades the new blacklist would have blocked
    patterns: list[PatternFinding] = field(default_factory=list)
    blocked_tickers: list[str] = field(default_factory=list)
    blocked_hours: list[int] = field(default_factory=list)
    blocked_days: list[int] = field(default_factory=list)
    rsi_ceiling: float | None = None   # new max RSI for LONG signals


@dataclass
class DebateResult:
    """Output of the Multi-Agent Debate Engine for a single trade signal."""
    ticker: str
    direction: str                  # "LONG" | "SHORT"
    bull_argument: str              # 1-sentence strongest bull point (Hebrew)
    bear_argument: str              # 1-sentence strongest bear point (Hebrew)
    judge_verdict: str              # 1-sentence final recommendation (Hebrew)
    confidence_score: int           # 0-100
    full_bull: str = ""             # full Bull Agent response
    full_bear: str = ""             # full Bear Agent response
    full_judge: str = ""            # full Judge Agent response
    full_visionary: str = ""        # full Visionary Agent response
    visionary_pattern: str = ""     # Hebrew pattern name (e.g., "דגל שורי")
    visionary_confirms: bool | None = None  # True=confirms signal, False=contradicts, None=skipped
    debated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class InsiderAlert:
    """A significant insider purchase surfaced by the Deep Data Engine."""
    ticker: str
    insider_name: str
    position: str
    shares: int
    value: float               # USD
    transaction_date: datetime
    source: str = "SEC / Yahoo Finance"


@dataclass
class OptionsFlowAlert:
    """Unusual options flow detected by the Deep Data Engine."""
    ticker: str
    expiry: str                # e.g. "2025-05-16"
    strike: float
    option_type: str           # "CALL" or "PUT"
    volume: int
    open_interest: int
    volume_oi_ratio: float     # volume / open_interest
    source: str = "Yahoo Finance"


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
