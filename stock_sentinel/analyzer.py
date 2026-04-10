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
)


def fetch_ohlcv(ticker: str, period: str = "60d", interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV from yfinance. Raises ValueError if empty.
    Flattens MultiIndex columns produced by yfinance 0.2.x.
    """
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        raise ValueError(f"No OHLCV data returned for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    return df


def compute_signals(ticker: str, df: pd.DataFrame) -> TechnicalSignal:
    """Compute RSI(14), SMA(20), SMA(50), ATR(14).
    Derive LONG/SHORT/NEUTRAL direction and Entry/SL/TP levels.
    Pre-injected columns (RSI_14, SMA_20, SMA_50) take precedence to support testing.
    """
    df = df.copy()

    MIN_ROWS = 50  # SMA(50) requires 50 rows
    if len(df) < MIN_ROWS:
        raise ValueError(
            f"DataFrame too short for {ticker}: {len(df)} rows, need at least {MIN_ROWS}"
        )

    if "RSI_14" not in df.columns:
        df.ta.rsi(length=14, append=True)
    if "SMA_20" not in df.columns:
        df.ta.sma(length=20, append=True)
    if "SMA_50" not in df.columns:
        df.ta.sma(length=50, append=True)
    if "ATRr_14" not in df.columns:
        df.ta.atr(length=14, append=True)

    latest = df.iloc[-1]
    close = float(latest["Close"])

    def _safe_get(series_val, default):
        return default if pd.isna(series_val) else float(series_val)

    rsi   = _safe_get(latest.get("RSI_14"),   50.0)
    ma_20 = _safe_get(latest.get("SMA_20"),   close)
    ma_50 = _safe_get(latest.get("SMA_50"),   close)
    atr   = _safe_get(latest.get("ATRr_14"),  close * 0.01)

    if rsi < RSI_OVERSOLD and close > ma_20:
        direction = "LONG"
    elif rsi > RSI_OVERBOUGHT and close < ma_20:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    if direction == "LONG":
        stop_loss = close - ATR_SL_MULTIPLIER * atr
        take_profit = close + ATR_TP_MULTIPLIER * atr
    elif direction == "SHORT":
        stop_loss = close + ATR_SL_MULTIPLIER * atr
        take_profit = close - ATR_TP_MULTIPLIER * atr
    else:
        stop_loss   = close - ATR_SL_MULTIPLIER * atr
        take_profit = close + ATR_TP_MULTIPLIER * atr

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
    )
