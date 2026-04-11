import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone
from stock_sentinel.models import TechnicalSignal
from stock_sentinel.config import (
    RSI_OVERSOLD,
    RSI_OVERBOUGHT,
    ATR_SL_MULTIPLIER,
    ATR_TP_MULTIPLIER,
    VOLUME_SPIKE_MULTIPLIER,
)


def fetch_ohlcv(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV from yfinance. Raises ValueError if empty.
    Flattens MultiIndex columns produced by yfinance 0.2.x.
    Default period extended to 1y so EMA(200) has sufficient history.
    """
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        raise ValueError(f"No OHLCV data returned for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    return df


def _detect_candlestick_pattern(df: pd.DataFrame) -> str:
    """Detect the most recent candlestick pattern in the last two bars.

    Priority: Bullish Engulfing > Hammer > Shooting Star.
    Returns "" if no pattern found.
    """
    if len(df) < 2:
        return ""

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    o, h, l, c = float(curr["Open"]), float(curr["High"]), float(curr["Low"]), float(curr["Close"])
    po, pc = float(prev["Open"]), float(prev["Close"])

    body_size = abs(c - o)
    total_range = h - l
    if total_range == 0:
        return ""

    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l

    # Bullish Engulfing: prev bar bearish, current bar bullish and fully covers prev body
    prev_bearish = po > pc
    curr_bullish = c > o
    if (prev_bearish and curr_bullish
            and o <= pc
            and c >= po):
        return "Bullish Engulfing"

    # Hammer: small body, lower shadow >= 2× body, upper shadow <= 10% of range
    if (body_size > 0
            and lower_shadow >= 2 * body_size
            and upper_shadow <= 0.1 * total_range):
        return "Hammer"

    # Shooting Star: small body, upper shadow >= 2× body, lower shadow <= 10% of range
    if (body_size > 0
            and upper_shadow >= 2 * body_size
            and lower_shadow <= 0.1 * total_range):
        return "Shooting Star"

    return ""


def _compute_technical_score(
    direction: str,
    ema_200_above: bool,
    pattern: str,
    volume_spike: bool,
    rsi: float,
    macd_bullish: bool,
) -> tuple[int, list[str]]:
    """Compute a 0-100 confluence score and the list of contributing factors.

    Scoring (direction-aware):
      +25  EMA 200 alignment (above for LONG, below for SHORT)
      +20  Candlestick pattern (bullish for LONG, bearish for SHORT)
      +20  Volume Spike
      +20  RSI alignment  (< 50 for LONG zone; > 50 for SHORT zone)
      +15  MACD alignment (bullish for LONG; bearish for SHORT)
    """
    score = 0
    factors: list[str] = []

    if direction == "LONG":
        if ema_200_above:
            score += 25
            factors.append("EMA 200 Trend")
        if pattern in ("Bullish Engulfing", "Hammer"):
            score += 20
            factors.append(f"Pattern: {pattern}")
        if volume_spike:
            score += 20
            factors.append("Volume Spike")
        if rsi < 50:
            score += 20
            factors.append(f"RSI {rsi:.1f} (bullish zone)")
        if macd_bullish:
            score += 15
            factors.append("MACD Bullish")

    elif direction == "SHORT":
        if not ema_200_above:
            score += 25
            factors.append("Price below EMA 200")
        if pattern == "Shooting Star":
            score += 20
            factors.append(f"Pattern: {pattern}")
        if volume_spike:
            score += 20
            factors.append("Volume Spike")
        if rsi > 50:
            score += 20
            factors.append(f"RSI {rsi:.1f} (bearish zone)")
        if not macd_bullish:
            score += 15
            factors.append("MACD Bearish")

    return score, factors


def compute_signals(ticker: str, df: pd.DataFrame) -> TechnicalSignal:
    """Compute RSI(14), SMA(20), SMA(50), EMA(200), ATR(14), VWAP(20), MACD.
    Detect candlestick patterns, volume spikes, and compute a confluence score.
    Pre-injected columns take precedence to support testing.
    """
    df = df.copy()

    MIN_ROWS = 50  # SMA(50) requires 50 rows
    if len(df) < MIN_ROWS:
        raise ValueError(
            f"DataFrame too short for {ticker}: {len(df)} rows, need at least {MIN_ROWS}"
        )

    # --- Core indicators (pre-injection support for tests) ---
    if "RSI_14" not in df.columns:
        df.ta.rsi(length=14, append=True)
    if "SMA_20" not in df.columns:
        df.ta.sma(length=20, append=True)
    if "SMA_50" not in df.columns:
        df.ta.sma(length=50, append=True)
    if "ATRr_14" not in df.columns:
        df.ta.atr(length=14, append=True)

    # --- EMA 200 (requires ~200 rows; NaN when insufficient history) ---
    if "EMA_200" not in df.columns:
        df.ta.ema(length=200, append=True)

    # --- MACD (12/26/9) ---
    if "MACD_12_26_9" not in df.columns:
        df.ta.macd(append=True)

    # --- Rolling VWAP (20-day volume-weighted typical price) ---
    if "VWAP_20" not in df.columns:
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        vol = df["Volume"].astype(float)
        df["VWAP_20"] = (typical * vol).rolling(20).sum() / vol.rolling(20).sum()

    # --- Volume Spike (current volume > N× 20-period average) ---
    vol_ma20 = df["Volume"].astype(float).rolling(20).mean()

    latest = df.iloc[-1]
    close = float(latest["Close"])

    def _safe_get(series_val, default):
        return default if pd.isna(series_val) else float(series_val)

    rsi   = _safe_get(latest.get("RSI_14"),   50.0)
    ma_20 = _safe_get(latest.get("SMA_20"),   close)
    ma_50 = _safe_get(latest.get("SMA_50"),   close)
    atr   = _safe_get(latest.get("ATRr_14"),  close * 0.01)
    ema_200 = _safe_get(latest.get("EMA_200"), 0.0)
    vwap   = _safe_get(latest.get("VWAP_20"), close)

    macd_val   = _safe_get(latest.get("MACD_12_26_9"),  0.0)
    macd_sig   = _safe_get(latest.get("MACDs_12_26_9"), 0.0)
    macd_bullish = macd_val > macd_sig

    vol_current = float(latest["Volume"])
    vol_avg = _safe_get(vol_ma20.iloc[-1], 0.0)
    volume_spike = vol_avg > 0 and vol_current > VOLUME_SPIKE_MULTIPLIER * vol_avg

    ema_200_valid = ema_200 > 0
    ema_200_above = ema_200_valid and close > ema_200

    # --- Direction ---
    if rsi < RSI_OVERSOLD and close > ma_20:
        direction = "LONG"
    elif rsi > RSI_OVERBOUGHT and close < ma_20:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    # --- SL / TP ---
    if direction == "LONG":
        stop_loss   = close - ATR_SL_MULTIPLIER * atr
        take_profit = close + ATR_TP_MULTIPLIER * atr
    elif direction == "SHORT":
        stop_loss   = close + ATR_SL_MULTIPLIER * atr
        take_profit = close - ATR_TP_MULTIPLIER * atr
    else:
        stop_loss   = close - ATR_SL_MULTIPLIER * atr
        take_profit = close + ATR_TP_MULTIPLIER * atr

    # --- Pattern + Score ---
    pattern = _detect_candlestick_pattern(df)
    technical_score, confluence_factors = _compute_technical_score(
        direction, ema_200_above, pattern, volume_spike, rsi, macd_bullish
    )

    return TechnicalSignal(
        ticker=ticker,
        rsi=rsi,
        ma_20=ma_20,
        ma_50=ma_50,
        atr=atr,
        entry=close,
        stop_loss=stop_loss,
        take_profit=take_profit,
        direction=direction,
        analyzed_at=datetime.now(timezone.utc),
        ema_200=ema_200,
        vwap=vwap,
        volume_spike=volume_spike,
        candlestick_pattern=pattern,
        macd_bullish=macd_bullish,
        technical_score=technical_score,
        confluence_factors=confluence_factors,
    )
