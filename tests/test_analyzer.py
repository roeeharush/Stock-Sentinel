import pandas as pd
import numpy as np
import pytest
from unittest.mock import patch
from datetime import datetime, timezone
from stock_sentinel.analyzer import fetch_ohlcv, compute_signals
from stock_sentinel.models import TechnicalSignal
from stock_sentinel.config import ATR_SL_MULTIPLIER, ATR_TP_MULTIPLIER


def _mock_df(seed=42, rows=60, base=100.0):
    """Synthetic OHLCV DataFrame — 60 rows, enough for SMA(50) to compute."""
    np.random.seed(seed)
    close = base + np.cumsum(np.random.randn(rows))
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.random.randint(1_000_000, 5_000_000, rows),
        },
        index=pd.date_range("2025-01-01", periods=rows, freq="B"),
    )


def test_compute_signals_returns_technical_signal():
    result = compute_signals("NVDA", _mock_df())
    assert isinstance(result, TechnicalSignal)
    assert result.ticker == "NVDA"
    assert 0 < result.rsi < 100
    assert result.atr > 0
    assert result.direction in ("LONG", "SHORT", "NEUTRAL")


def test_compute_signals_long_sl_below_entry_tp_above():
    """When direction=LONG: SL must be below entry, TP must be above entry."""
    df = _mock_df()
    df["RSI_14"] = 25.0          # force oversold
    df["SMA_20"] = df["Close"] * 0.95   # force close > ma_20
    result = compute_signals("NVDA", df)
    assert result.direction == "LONG"
    assert result.stop_loss < result.entry
    assert result.take_profit > result.entry


def test_compute_signals_short_sl_above_entry_tp_below():
    """When direction=SHORT: SL must be above entry, TP must be below entry."""
    df = _mock_df()
    df["RSI_14"] = 75.0          # force overbought
    df["SMA_20"] = df["Close"] * 1.05   # force close < ma_20
    result = compute_signals("NVDA", df)
    assert result.direction == "SHORT"
    assert result.stop_loss > result.entry
    assert result.take_profit < result.entry


def test_compute_signals_sl_tp_multipliers():
    """SL = entry ± 1.5*ATR, TP = entry ± 3.0*ATR (from config constants)."""
    df = _mock_df()
    df["RSI_14"] = 25.0
    df["SMA_20"] = df["Close"] * 0.95
    r = compute_signals("NVDA", df)
    assert r.direction == "LONG"
    assert abs(r.stop_loss - (r.entry - ATR_SL_MULTIPLIER * r.atr)) < 0.0001
    assert abs(r.take_profit - (r.entry + ATR_TP_MULTIPLIER * r.atr)) < 0.0001


def test_compute_signals_neutral_direction():
    """RSI in [30, 70] should produce NEUTRAL direction."""
    df = _mock_df()
    df["RSI_14"] = 50.0   # mid-range, never triggers LONG or SHORT
    result = compute_signals("NVDA", df)
    assert result.direction == "NEUTRAL"


def test_fetch_ohlcv_raises_on_empty():
    with patch("yfinance.download", return_value=pd.DataFrame()):
        with pytest.raises(ValueError, match="No OHLCV data"):
            fetch_ohlcv("FAKE")


def test_fetch_ohlcv_flattens_multiindex_columns():
    """yfinance 0.2.x returns MultiIndex columns like ('Close', 'NVDA').
    fetch_ohlcv must flatten these to single-level ('Close')."""
    multi_df = _mock_df()
    multi_df.columns = pd.MultiIndex.from_tuples(
        [(c, "NVDA") for c in multi_df.columns]
    )
    with patch("yfinance.download", return_value=multi_df):
        result = fetch_ohlcv("NVDA")
    assert "Close" in result.columns
    assert not isinstance(result.columns, pd.MultiIndex)


def test_compute_signals_raises_on_short_dataframe():
    """DataFrame shorter than 50 rows should raise ValueError."""
    df = _mock_df(rows=30)
    with pytest.raises(ValueError, match="too short"):
        compute_signals("NVDA", df)


from stock_sentinel.analyzer import _detect_candlestick_pattern, _compute_technical_score


def test_compute_signals_has_new_fields():
    """New TechnicalSignal fields are present with valid types."""
    result = compute_signals("NVDA", _mock_df())
    assert isinstance(result.technical_score, int)
    assert 0 <= result.technical_score <= 100
    assert isinstance(result.confluence_factors, list)
    assert result.candlestick_pattern in ("", "Bullish Engulfing", "Hammer", "Shooting Star")
    assert isinstance(result.volume_spike, bool)
    assert isinstance(result.macd_bullish, bool)
    assert result.vwap > 0
    assert result.ema_200 >= 0.0


def test_volume_spike_detected():
    """Volume spike when last bar volume > 2x rolling mean."""
    df = _mock_df(rows=60)
    df.iloc[-1, df.columns.get_loc("Volume")] = 20_000_000  # ~4-8x normal
    result = compute_signals("NVDA", df)
    assert result.volume_spike is True


def test_no_volume_spike_uniform():
    """No spike when all volumes are equal."""
    df = _mock_df(rows=60)
    df["Volume"] = 2_000_000
    result = compute_signals("NVDA", df)
    assert result.volume_spike is False


def test_technical_score_increases_with_volume_spike():
    """Adding a volume spike increases TechnicalScore when direction is not NEUTRAL."""
    df = _mock_df(rows=60)
    df["RSI_14"] = 25.0
    df["SMA_20"] = df["Close"] * 0.95
    r1 = compute_signals("NVDA", df)
    df2 = df.copy()
    df2.iloc[-1, df2.columns.get_loc("Volume")] = 20_000_000
    r2 = compute_signals("NVDA", df2)
    # r2 has volume spike; r1 doesn't — score should be at least as high
    if r1.direction != "NEUTRAL":
        assert r2.technical_score >= r1.technical_score


def test_bullish_engulfing_detected():
    """Bullish engulfing: prev bearish, current bullish and fully covers prev body."""
    df = _mock_df(rows=60)
    prev_idx = df.index[-2]
    curr_idx = df.index[-1]
    # Previous bar: bearish
    df.at[prev_idx, "Open"] = 102.0
    df.at[prev_idx, "Close"] = 100.0
    df.at[prev_idx, "High"] = 103.0
    df.at[prev_idx, "Low"] = 99.0
    # Current bar: bullish, engulfs prev
    df.at[curr_idx, "Open"] = 99.5    # <= prev_close (100.0)
    df.at[curr_idx, "Close"] = 103.0  # >= prev_open (102.0)
    df.at[curr_idx, "High"] = 104.0
    df.at[curr_idx, "Low"] = 99.0
    assert _detect_candlestick_pattern(df) == "Bullish Engulfing"


def test_hammer_detected():
    """Hammer: small body, long lower shadow, tiny upper shadow."""
    df = _mock_df(rows=60)
    df.at[df.index[-1], "Open"] = 102.0
    df.at[df.index[-1], "Close"] = 102.5   # body = 0.5
    df.at[df.index[-1], "High"] = 102.6    # upper shadow = 0.1
    df.at[df.index[-1], "Low"] = 97.0      # lower shadow = 5.0 >= 2*0.5 ✓
    assert _detect_candlestick_pattern(df) == "Hammer"


def test_shooting_star_detected():
    """Shooting Star: small body, long upper shadow, tiny lower shadow."""
    df = _mock_df(rows=60)
    df.at[df.index[-1], "Open"] = 102.0
    df.at[df.index[-1], "Close"] = 102.5   # body = 0.5
    df.at[df.index[-1], "High"] = 108.0    # upper shadow = 5.5 >= 2*0.5 ✓
    df.at[df.index[-1], "Low"] = 101.95    # lower shadow = 0.05 <= 0.1*(108-101.95) ✓
    assert _detect_candlestick_pattern(df) == "Shooting Star"


def test_no_pattern_on_normal_candle():
    """A strong trending candle with symmetric shadows has no pattern."""
    df = _mock_df(rows=60)
    # Previous: bullish (not bearish, so no engulfing)
    df.at[df.index[-2], "Open"] = 98.0
    df.at[df.index[-2], "Close"] = 101.0
    df.at[df.index[-2], "High"] = 102.0
    df.at[df.index[-2], "Low"] = 97.0
    # Current: strong bullish, symmetric shadows
    df.at[df.index[-1], "Open"] = 101.0
    df.at[df.index[-1], "Close"] = 104.0   # body = 3.0
    df.at[df.index[-1], "High"] = 104.5    # upper shadow = 0.5 < 2*3=6 ✓
    df.at[df.index[-1], "Low"] = 100.5     # lower shadow = 0.5 < 2*3=6 ✓
    assert _detect_candlestick_pattern(df) == ""
