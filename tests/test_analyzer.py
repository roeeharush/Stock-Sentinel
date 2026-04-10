import pandas as pd
import numpy as np
import pytest
from unittest.mock import patch
from datetime import datetime, timezone
from stock_sentinel.analyzer import fetch_ohlcv, compute_signals
from stock_sentinel.models import TechnicalSignal


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
    expected_sl = r.entry - 1.5 * r.atr
    expected_tp = r.entry + 3.0 * r.atr
    assert abs(r.stop_loss - expected_sl) < 0.0001
    assert abs(r.take_profit - expected_tp) < 0.0001


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
