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

    if "RSI_14" not in df.columns:
        df.ta.rsi(length=14, append=True)
    if "SMA_20" not in df.columns:
        df.ta.sma(length=20, append=True)
    if "SMA_50" not in df.columns:
        df.ta.sma(length=50, append=True)
    df.ta.atr(length=14, append=True)

    latest = df.iloc[-1]
    rsi = float(latest.get("RSI_14", 50.0))
    ma_20 = float(latest.get("SMA_20", latest["Close"]))
    ma_50 = float(latest.get("SMA_50", latest["Close"]))
    atr = float(latest.get("ATRr_14", latest["Close"] * 0.01))
    close = float(latest["Close"])

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
        stop_loss = close - atr
        take_profit = close + atr

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
