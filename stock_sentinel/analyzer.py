import numpy as np
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone
from stock_sentinel.models import TechnicalSignal
from stock_sentinel.config import (
    RSI_OVERSOLD,
    RSI_OVERBOUGHT,
    ATR_SL_MULTIPLIER,
    ATR_TP1_MULTIPLIER,
    ATR_TP2_MULTIPLIER,
    ATR_TP3_MULTIPLIER,
    ATR_TP_MULTIPLIER,
    VOLUME_SPIKE_MULTIPLIER,
    SCORE_WEIGHT_EMA200,
    SCORE_WEIGHT_PATTERN,
    SCORE_WEIGHT_VOLUME,
    SCORE_WEIGHT_RSI,
    SCORE_WEIGHT_MACD,
    ADX_TREND_MIN,
    OBV_SLOPE_BARS,
    RR_MIN,
    ATR_PCT_HIGH_THRESHOLD,
)


def fetch_ohlcv(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV from yfinance. Raises ValueError if empty.
    Flattens MultiIndex columns produced by yfinance 0.2.x.
    Default period 1y gives ~252 rows — enough for EMA(200).
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
    if (prev_bearish and curr_bullish and o <= pc and c >= po):
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
    """Compute a 0-100 confluence score and contributing factors."""
    score = 0
    factors: list[str] = []

    if direction == "LONG":
        if ema_200_above:
            score += SCORE_WEIGHT_EMA200
            factors.append("EMA 200 Trend")
        if pattern in ("Bullish Engulfing", "Hammer"):
            score += SCORE_WEIGHT_PATTERN
            factors.append(f"Pattern: {pattern}")
        if volume_spike:
            score += SCORE_WEIGHT_VOLUME
            factors.append("Volume Spike")
        if rsi < 50:
            score += SCORE_WEIGHT_RSI
            factors.append(f"RSI {rsi:.1f} (bullish zone)")
        if macd_bullish:
            score += SCORE_WEIGHT_MACD
            factors.append("MACD Bullish")

    elif direction == "SHORT":
        if not ema_200_above:
            score += SCORE_WEIGHT_EMA200
            factors.append("Price below EMA 200")
        if pattern == "Shooting Star":
            score += SCORE_WEIGHT_PATTERN
            factors.append(f"Pattern: {pattern}")
        if volume_spike:
            score += SCORE_WEIGHT_VOLUME
            factors.append("Volume Spike")
        if rsi > 50:
            score += SCORE_WEIGHT_RSI
            factors.append(f"RSI {rsi:.1f} (bearish zone)")
        if not macd_bullish:
            score += SCORE_WEIGHT_MACD
            factors.append("MACD Bearish")

    return score, factors


def _classify_horizon(
    direction: str,
    volume_spike: bool,
    bb_breakout: bool,
    stochrsi_crossover: bool,
    ema_200_above: bool,
    adx_strong: bool,
    obv_rising: bool,
    ema_21_break: bool = False,
    atr_pct_high: bool = False,
) -> str:
    """Return trade horizon: 'SHORT_TERM', 'LONG_TERM', 'BOTH', or ''.

    SHORT_TERM (2-10 days): any momentum signal present, including
        EMA 21 break (Task 17.2) or high ATR% volatility.
    LONG_TERM (3-8 weeks): price > EMA200 + Golden Cross (SMA50>EMA200) + positive OBV.
    """
    short = volume_spike or bb_breakout or stochrsi_crossover or ema_21_break or atr_pct_high
    long = ema_200_above and adx_strong and obv_rising
    if short and long:
        return "BOTH"
    if short:
        return "SHORT_TERM"
    if long:
        return "LONG_TERM"
    return ""


def _build_horizon_reason(
    horizon: str,
    volume_spike: bool,
    bb_breakout: bool,
    stochrsi_crossover: bool,
    ema_200_above: bool,
    adx_strong: bool,
    obv_rising: bool,
    ema_21_break: bool = False,
    atr_pct_high: bool = False,
) -> str:
    """Generate a Hebrew explanation sentence for the trade horizon."""
    if not horizon:
        return ""

    short_parts = []
    if volume_spike:
        short_parts.append("פריצת ווליום")
    if bb_breakout:
        short_parts.append("פריצת רצועות בולינגר")
    if stochrsi_crossover:
        short_parts.append("חצייה של RSI סטוכסטי")
    if ema_21_break:
        short_parts.append("פריצת EMA 21")
    if atr_pct_high:
        short_parts.append("תנודתיות גבוהה (ATR%)")

    long_parts = []
    if ema_200_above:
        long_parts.append("מחיר מעל EMA 200")
    if adx_strong:
        long_parts.append("ADX חזק")
    if obv_rising:
        long_parts.append("נפח מצטבר עולה")

    if horizon == "SHORT_TERM" and short_parts:
        signals = " ו-".join(short_parts)
        return f"המניה מציגה {signals} — אות מומנטום לטווח קצר (2-10 ימי מסחר)."
    if horizon == "LONG_TERM" and long_parts:
        signals = " ו-".join(long_parts)
        return f"המניה מציגה {signals} — אות מגמה לטווח ארוך (3-8 שבועות)."
    if horizon == "BOTH":
        short_str = " ו-".join(short_parts) if short_parts else "אותות מומנטום"
        long_str = " ו-".join(long_parts) if long_parts else "אותות מגמה"
        return f"אות כפול: {short_str} בתמיכת {long_str} — הזדמנות לטווח קצר (2-10 ימים) וארוך (3-8 שבועות) כאחד."
    return ""


def _compute_pivot_points(df: pd.DataFrame) -> tuple[float, float, float, float]:
    """Standard floor pivot points using the previous bar's High / Low / Close.

    Returns (R1, R2, S1, S2).
    """
    if len(df) < 2:
        return 0.0, 0.0, 0.0, 0.0
    prev = df.iloc[-2]
    h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
    pivot = (h + l + c) / 3.0
    r1 = round(2.0 * pivot - l, 2)
    r2 = round(pivot + (h - l), 2)
    s1 = round(2.0 * pivot - h, 2)
    s2 = round(pivot - (h - l), 2)
    return r1, r2, s1, s2


def _detect_rsi_divergence(df: pd.DataFrame, periods: int = 14) -> str:
    """Detect RSI divergence over the last *periods* bars (excluding the live bar).

    Bullish divergence: price makes a lower low but RSI makes a higher low.
    Bearish divergence: price makes a higher high but RSI makes a lower high.
    Returns 'bullish', 'bearish', or ''.
    """
    rsi_col = "RSI_14"
    if rsi_col not in df.columns or len(df) < periods + 2:
        return ""

    window = df.iloc[-(periods + 1):-1]       # *periods* complete bars
    close_vals = window["Close"].values.astype(float)
    rsi_vals   = window[rsi_col].values.astype(float)

    if np.isnan(rsi_vals).any():
        return ""

    half = periods // 2
    first_close, second_close = close_vals[:half], close_vals[half:]
    first_rsi,   second_rsi   = rsi_vals[:half],   rsi_vals[half:]

    # Bullish: lower price low, higher RSI low
    if second_close.min() < first_close.min() and second_rsi.min() > first_rsi.min():
        return "bullish"

    # Bearish: higher price high, lower RSI high
    if second_close.max() > first_close.max() and second_rsi.max() < first_rsi.max():
        return "bearish"

    return ""


def _compute_poc(df: pd.DataFrame, bins: int = 20) -> float:
    """Volume Profile — return the price at the Point of Control (highest-volume bin)."""
    prices  = df["Close"].values.astype(float)
    volumes = df["Volume"].values.astype(float)
    p_min, p_max = prices.min(), prices.max()
    if p_min >= p_max:
        return round(float(prices[-1]), 2)

    edges    = np.linspace(p_min, p_max, bins + 1)
    bin_vols = np.zeros(bins)
    for price, vol in zip(prices, volumes):
        idx = min(int((price - p_min) / (p_max - p_min) * bins), bins - 1)
        bin_vols[idx] += vol

    poc_bin   = int(np.argmax(bin_vols))
    poc_price = (edges[poc_bin] + edges[poc_bin + 1]) / 2.0
    return round(float(poc_price), 2)


def _compute_fibonacci(df: pd.DataFrame, lookback: int = 20) -> tuple[float, float]:
    """Fibonacci Golden Pocket retracement levels (61.8% and 65.0%).

    Measures swing high / low over the last *lookback* bars.
    Returns (fib_618, fib_65).  Both are 0.0 if swing is zero.
    """
    window = df.tail(lookback)
    high   = float(window["High"].max())
    low    = float(window["Low"].min())
    swing  = high - low
    if swing <= 0:
        return 0.0, 0.0
    fib_618 = round(high - 0.618 * swing, 2)
    fib_65  = round(high - 0.650 * swing, 2)
    return fib_618, fib_65


def compute_signals(ticker: str, df: pd.DataFrame) -> TechnicalSignal:
    """Compute all technical indicators and return a fully-populated TechnicalSignal."""
    df = df.copy()

    MIN_ROWS = 50
    if len(df) < MIN_ROWS:
        raise ValueError(
            f"DataFrame too short for {ticker}: {len(df)} rows, need at least {MIN_ROWS}"
        )

    def _safe_get(val, default):
        return default if (val is None or pd.isna(val)) else float(val)

    # ── Core indicators (pre-injection support for tests) ──────────────────────
    if "RSI_14" not in df.columns:
        df.ta.rsi(length=14, append=True)
    if "SMA_20" not in df.columns:
        df.ta.sma(length=20, append=True)
    if "SMA_50" not in df.columns:
        df.ta.sma(length=50, append=True)
    if "ATRr_14" not in df.columns:
        df.ta.atr(length=14, append=True)

    # ── EMA 200 ────────────────────────────────────────────────────────────────
    if "EMA_200" not in df.columns:
        df.ta.ema(length=200, append=True)

    # ── MACD ──────────────────────────────────────────────────────────────────
    if "MACD_12_26_9" not in df.columns:
        df.ta.macd(append=True)

    # ── Bollinger Bands (20, 2σ) ───────────────────────────────────────────────
    if "BBU_20_2.0" not in df.columns:
        df.ta.bbands(length=20, std=2.0, append=True)

    # ── Stochastic RSI ─────────────────────────────────────────────────────────
    if "STOCHRSIk_14_14_3_3" not in df.columns:
        df.ta.stochrsi(length=14, rsi_length=14, k=3, d=3, append=True)

    # ── ADX ────────────────────────────────────────────────────────────────────
    if "ADX_14" not in df.columns:
        df.ta.adx(length=14, append=True)

    # ── OBV ────────────────────────────────────────────────────────────────────
    if "OBV" not in df.columns:
        df.ta.obv(append=True)

    # ── EMA 21 (short-term momentum line) ─────────────────────────────────────
    if "EMA_21" not in df.columns:
        df.ta.ema(length=21, append=True)

    # ── Rolling VWAP (20-day) ──────────────────────────────────────────────────
    if "VWAP_20" not in df.columns:
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        vol = df["Volume"].astype(float)
        df["VWAP_20"] = (typical * vol).rolling(20).sum() / vol.rolling(20).sum()

    # ── Volume Spike ───────────────────────────────────────────────────────────
    vol_ma20 = df["Volume"].astype(float).rolling(20).mean()

    latest = df.iloc[-1]
    close = float(latest["Close"])

    rsi    = _safe_get(latest.get("RSI_14"),   50.0)
    ma_20  = _safe_get(latest.get("SMA_20"),   close)
    ma_50  = _safe_get(latest.get("SMA_50"),   close)
    atr    = _safe_get(latest.get("ATRr_14"),  close * 0.01)
    ema_200 = _safe_get(latest.get("EMA_200"), 0.0)
    vwap   = _safe_get(latest.get("VWAP_20"), close)

    ema_21 = _safe_get(latest.get("EMA_21"), close)

    macd_val = _safe_get(latest.get("MACD_12_26_9"),  0.0)
    macd_sig = _safe_get(latest.get("MACDs_12_26_9"), 0.0)
    macd_bullish = macd_val > macd_sig

    vol_current = float(latest["Volume"])
    vol_avg = _safe_get(vol_ma20.iloc[-1], 0.0)
    volume_spike = vol_avg > 0 and vol_current > VOLUME_SPIKE_MULTIPLIER * vol_avg

    ema_200_valid = ema_200 > 0
    ema_200_above = ema_200_valid and close > ema_200

    # ── BB breakout ────────────────────────────────────────────────────────────
    bbu = _safe_get(latest.get("BBU_20_2.0"), None)
    bbl = _safe_get(latest.get("BBL_20_2.0"), None)
    bb_breakout_long  = bbu is not None and close > bbu
    bb_breakout_short = bbl is not None and close < bbl

    # ── Stochastic RSI crossover ───────────────────────────────────────────────
    stochrsi_crossover = False
    if len(df) >= 2:
        k_col = "STOCHRSIk_14_14_3_3"
        d_col = "STOCHRSId_14_14_3_3"
        if k_col in df.columns and d_col in df.columns:
            curr_k = _safe_get(df[k_col].iloc[-1], None)
            curr_d = _safe_get(df[d_col].iloc[-1], None)
            prev_k = _safe_get(df[k_col].iloc[-2], None)
            prev_d = _safe_get(df[d_col].iloc[-2], None)
            if None not in (curr_k, curr_d, prev_k, prev_d):
                bullish_cross = prev_k <= prev_d and curr_k > curr_d and curr_k < 80
                bearish_cross = prev_k >= prev_d and curr_k < curr_d and curr_k > 20
                stochrsi_crossover = bullish_cross or bearish_cross

    # ── ADX ────────────────────────────────────────────────────────────────────
    adx_val = _safe_get(latest.get("ADX_14"), 0.0)
    adx_strong = adx_val > ADX_TREND_MIN

    # ── OBV slope ──────────────────────────────────────────────────────────────
    obv_rising = False
    if "OBV" in df.columns and len(df) >= OBV_SLOPE_BARS:
        obv_now  = _safe_get(df["OBV"].iloc[-1],            None)
        obv_past = _safe_get(df["OBV"].iloc[-OBV_SLOPE_BARS], None)
        if obv_now is not None and obv_past is not None:
            obv_rising = obv_now > obv_past

    # ── Direction ──────────────────────────────────────────────────────────────
    if rsi < RSI_OVERSOLD and close > ma_20:
        direction = "LONG"
    elif rsi > RSI_OVERBOUGHT and close < ma_20:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    # ── BB breakout aligned with direction ─────────────────────────────────────
    bb_breakout = (direction == "LONG" and bb_breakout_long) or \
                  (direction == "SHORT" and bb_breakout_short)

    # ── StochRSI crossover aligned with direction ──────────────────────────────
    # (already direction-agnostic from above; refine for direction)
    if len(df) >= 2 and "STOCHRSIk_14_14_3_3" in df.columns:
        k_col = "STOCHRSIk_14_14_3_3"
        d_col = "STOCHRSId_14_14_3_3"
        curr_k = _safe_get(df[k_col].iloc[-1], None)
        curr_d = _safe_get(df[d_col].iloc[-1], None)
        prev_k = _safe_get(df[k_col].iloc[-2], None)
        prev_d = _safe_get(df[d_col].iloc[-2], None)
        if None not in (curr_k, curr_d, prev_k, prev_d):
            if direction == "LONG":
                stochrsi_crossover = prev_k <= prev_d and curr_k > curr_d and curr_k < 80
            elif direction == "SHORT":
                stochrsi_crossover = prev_k >= prev_d and curr_k < curr_d and curr_k > 20
            else:
                stochrsi_crossover = False

    # ── Triple targets ─────────────────────────────────────────────────────────
    if direction == "LONG":
        stop_loss    = close - ATR_SL_MULTIPLIER  * atr
        take_profit_1 = close + ATR_TP1_MULTIPLIER * atr
        take_profit   = close + ATR_TP2_MULTIPLIER * atr
        take_profit_3 = close + ATR_TP3_MULTIPLIER * atr
    elif direction == "SHORT":
        stop_loss    = close + ATR_SL_MULTIPLIER  * atr
        take_profit_1 = close - ATR_TP1_MULTIPLIER * atr
        take_profit   = close - ATR_TP2_MULTIPLIER * atr
        take_profit_3 = close - ATR_TP3_MULTIPLIER * atr
    else:
        stop_loss    = close - ATR_SL_MULTIPLIER  * atr
        take_profit_1 = close + ATR_TP1_MULTIPLIER * atr
        take_profit   = close + ATR_TP2_MULTIPLIER * atr
        take_profit_3 = close + ATR_TP3_MULTIPLIER * atr

    # ── EMA 21 break (price crossed through EMA21 aligned with direction) ───────
    ema_21_break = False
    if ema_21 > 0 and len(df) >= 2:
        prev_close = float(df["Close"].iloc[-2])
        if direction == "LONG":
            ema_21_break = prev_close <= ema_21 < close   # crossed above
        elif direction == "SHORT":
            ema_21_break = prev_close >= ema_21 > close   # crossed below

    # ── ATR as percentage of close ─────────────────────────────────────────────
    atr_pct = (atr / close * 100.0) if close > 0 else 0.0
    atr_pct_high = atr_pct >= ATR_PCT_HIGH_THRESHOLD

    # ── Candlestick pattern + TechnicalScore ───────────────────────────────────
    pattern = _detect_candlestick_pattern(df)
    technical_score, confluence_factors = _compute_technical_score(
        direction, ema_200_above, pattern, volume_spike, rsi, macd_bullish
    )

    # ── Horizon classification ─────────────────────────────────────────────────
    horizon = _classify_horizon(
        direction, volume_spike, bb_breakout, stochrsi_crossover,
        ema_200_above, adx_strong, obv_rising,
        ema_21_break=ema_21_break,
        atr_pct_high=atr_pct_high,
    )
    horizon_reason = _build_horizon_reason(
        horizon, volume_spike, bb_breakout, stochrsi_crossover,
        ema_200_above, adx_strong, obv_rising,
        ema_21_break=ema_21_break,
        atr_pct_high=atr_pct_high,
    )

    # ── Task 17.2: Risk/Reward ratio ───────────────────────────────────────────
    # RR = (TP1 - entry) / (entry - SL)  for LONG
    #     (entry - TP1) / (SL - entry)  for SHORT
    risk  = abs(close - stop_loss)
    rward = abs(take_profit_1 - close)
    risk_reward = round(rward / risk, 2) if risk > 0 else 0.0

    # ── Task 16: Expert Tier indicators ────────────────────────────────────────
    pivot_r1, pivot_r2, pivot_s1, pivot_s2 = _compute_pivot_points(df)
    rsi_divergence = _detect_rsi_divergence(df)
    poc_price      = _compute_poc(df)
    fib_618, fib_65 = _compute_fibonacci(df)
    golden_cross   = (ma_50 > 0 and ema_200 > 0 and ma_50 > ema_200)

    # Append Expert Tier signals as informational confluence factors
    if golden_cross:
        confluence_factors.append("Golden Cross")
    if rsi_divergence == "bullish":
        confluence_factors.append("Bullish Divergence")
    elif rsi_divergence == "bearish":
        confluence_factors.append("Bearish Divergence")

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
        take_profit_1=take_profit_1,
        take_profit_3=take_profit_3,
        bb_breakout=bb_breakout,
        stochrsi_crossover=stochrsi_crossover,
        adx_strong=adx_strong,
        obv_rising=obv_rising,
        horizon=horizon,
        horizon_reason=horizon_reason,
        pivot_r1=pivot_r1,
        pivot_r2=pivot_r2,
        pivot_s1=pivot_s1,
        pivot_s2=pivot_s2,
        rsi_divergence=rsi_divergence,
        poc_price=poc_price,
        golden_cross=golden_cross,
        fib_618=fib_618,
        fib_65=fib_65,
        ema_21=ema_21,
        ema_21_break=ema_21_break,
        atr_pct=atr_pct,
        risk_reward=risk_reward,
    )
