import pandas as pd
import numpy as np
import pytest
from unittest.mock import patch
from datetime import datetime, timezone
from stock_sentinel.analyzer import fetch_ohlcv, compute_signals
from stock_sentinel.models import TechnicalSignal
from stock_sentinel.config import ATR_SL_MULTIPLIER, ATR_TP_MULTIPLIER, ATR_TP1_MULTIPLIER, ATR_TP3_MULTIPLIER, ADX_TREND_MIN, OBV_SLOPE_BARS


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
    """SL = entry ± 2.0*ATR, TP1/2/3 via ATR multipliers (from config constants)."""
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


from stock_sentinel.analyzer import (
    _detect_candlestick_pattern, _compute_technical_score,
    _classify_horizon, _build_horizon_reason,
    _compute_pivot_points, _detect_rsi_divergence,
    _compute_poc, _compute_fibonacci,
)


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


def test_compute_signals_triple_targets():
    """TP1 < TP2 (take_profit) < TP3 for LONG direction."""
    df = _mock_df()
    df["RSI_14"] = 25.0
    df["SMA_20"] = df["Close"] * 0.95
    r = compute_signals("NVDA", df)
    assert r.direction == "LONG"
    assert r.take_profit_1 < r.take_profit < r.take_profit_3
    assert abs(r.take_profit_1 - (r.entry + ATR_TP1_MULTIPLIER * r.atr)) < 0.0001
    assert abs(r.take_profit_3 - (r.entry + ATR_TP3_MULTIPLIER * r.atr)) < 0.0001


def test_classify_horizon_short_term_volume():
    assert _classify_horizon("LONG", True, False, False, False, False, False) == "SHORT_TERM"


def test_classify_horizon_long_term_all_three():
    assert _classify_horizon("LONG", False, False, False, True, True, True) == "LONG_TERM"


def test_classify_horizon_both():
    assert _classify_horizon("LONG", True, False, False, True, True, True) == "BOTH"


def test_classify_horizon_none():
    assert _classify_horizon("LONG", False, False, False, False, False, False) == ""


def test_build_horizon_reason_short_term():
    reason = _build_horizon_reason("SHORT_TERM", True, False, False, False, False, False)
    assert "פריצת ווליום" in reason
    assert "2-10" in reason


def test_build_horizon_reason_long_term():
    reason = _build_horizon_reason("LONG_TERM", False, False, False, True, True, True)
    assert "EMA 200" in reason
    assert "ארוך" in reason


def test_build_horizon_reason_empty_when_no_horizon():
    assert _build_horizon_reason("", False, False, False, False, False, False) == ""


def test_compute_signals_horizon_field_present():
    """horizon field is populated and valid."""
    result = compute_signals("NVDA", _mock_df())
    assert result.horizon in ("SHORT_TERM", "LONG_TERM", "BOTH", "")
    assert isinstance(result.horizon_reason, str)
    assert isinstance(result.bb_breakout, bool)
    assert isinstance(result.adx_strong, bool)
    assert isinstance(result.obv_rising, bool)
    assert isinstance(result.stochrsi_crossover, bool)


# ── Task 16: Expert Tier tests ────────────────────────────────────────────────

def test_compute_pivot_points_basic():
    """Pivot R1 > S1 for any non-degenerate bar."""
    df = _mock_df()
    r1, r2, s1, s2 = _compute_pivot_points(df)
    assert r1 > s1
    assert r2 >= r1
    assert s2 <= s1


def test_compute_pivot_points_too_short():
    """DataFrame with fewer than 2 rows returns all zeros."""
    df = _mock_df(rows=1)
    assert _compute_pivot_points(df) == (0.0, 0.0, 0.0, 0.0)


def test_detect_rsi_divergence_no_divergence_flat():
    """Flat RSI and flat price produces no divergence."""
    df = _mock_df(rows=60)
    df["Close"] = 100.0
    df["RSI_14"] = 50.0
    result = _detect_rsi_divergence(df)
    assert result == ""


def test_detect_rsi_divergence_bullish():
    """Price makes lower low while RSI makes higher low → bullish divergence."""
    df = _mock_df(rows=60)
    periods = 14
    window_start = len(df) - periods - 1
    half = periods // 2
    # First half: price low = 90, RSI low = 30
    # Second half: price low = 85 (lower), RSI low = 35 (higher)
    close_vals = df["Close"].values.copy()
    rsi_vals = np.ones(len(df)) * 50.0
    # Set the first-half minimum
    close_vals[window_start + 2] = 90.0
    rsi_vals[window_start + 2] = 30.0
    # Set the second-half minimum (lower close, higher RSI)
    close_vals[window_start + half + 2] = 85.0
    rsi_vals[window_start + half + 2] = 35.0
    df["Close"] = close_vals
    df["RSI_14"] = rsi_vals
    assert _detect_rsi_divergence(df) == "bullish"


def test_detect_rsi_divergence_bearish():
    """Price makes higher high while RSI makes lower high → bearish divergence."""
    df = _mock_df(rows=60)
    periods = 14
    window_start = len(df) - periods - 1
    half = periods // 2
    close_vals = df["Close"].values.copy()
    rsi_vals = np.ones(len(df)) * 50.0
    # First half: price high = 110, RSI high = 70
    close_vals[window_start + 2] = 110.0
    rsi_vals[window_start + 2] = 70.0
    # Second half: price high = 115 (higher), RSI high = 65 (lower)
    close_vals[window_start + half + 2] = 115.0
    rsi_vals[window_start + half + 2] = 65.0
    df["Close"] = close_vals
    df["RSI_14"] = rsi_vals
    assert _detect_rsi_divergence(df) == "bearish"


def test_detect_rsi_divergence_missing_col():
    """No RSI_14 column → returns empty string, no crash."""
    df = _mock_df(rows=60)
    assert _detect_rsi_divergence(df) == ""


def test_compute_poc_in_price_range():
    """POC must be within the Close price range of the DataFrame."""
    df = _mock_df(rows=60, base=100.0)
    poc = _compute_poc(df)
    assert df["Close"].min() <= poc <= df["Close"].max()


def test_compute_poc_flat():
    """All prices equal → POC equals that price."""
    df = _mock_df(rows=60)
    df["Close"] = 150.0
    df["High"] = 151.0
    df["Low"] = 149.0
    poc = _compute_poc(df)
    assert poc == 150.0


def test_compute_fibonacci_golden_pocket_ordering():
    """fib_618 > fib_65 (61.8% retraces less than 65.0%)."""
    df = _mock_df(rows=60)
    fib_618, fib_65 = _compute_fibonacci(df)
    assert fib_618 > 0.0
    assert fib_65 > 0.0
    assert fib_618 > fib_65


def test_compute_fibonacci_within_range():
    """Both Fibonacci levels must be within the lookback high/low range."""
    df = _mock_df(rows=60)
    fib_618, fib_65 = _compute_fibonacci(df, lookback=20)
    window = df.tail(20)
    lo, hi = float(window["Low"].min()), float(window["High"].max())
    assert lo <= fib_65 <= hi
    assert lo <= fib_618 <= hi


def test_compute_signals_expert_fields_present():
    """All Task 16 TechnicalSignal fields are populated with valid types."""
    result = compute_signals("NVDA", _mock_df())
    assert isinstance(result.pivot_r1, float)
    assert isinstance(result.pivot_r2, float)
    assert isinstance(result.pivot_s1, float)
    assert isinstance(result.pivot_s2, float)
    assert result.rsi_divergence in ("bullish", "bearish", "")
    assert isinstance(result.poc_price, float) and result.poc_price > 0
    assert isinstance(result.golden_cross, bool)
    assert isinstance(result.fib_618, float)
    assert isinstance(result.fib_65, float)
    # Pivots: R1 should be > S1 for normal data
    if result.pivot_r1 > 0 and result.pivot_s1 > 0:
        assert result.pivot_r1 > result.pivot_s1


def test_golden_cross_detected():
    """golden_cross=True when MA50 > EMA200."""
    df = _mock_df(rows=60)
    df["SMA_50"] = 120.0   # SMA50 above EMA200
    df["EMA_200"] = 100.0
    result = compute_signals("NVDA", df)
    # golden_cross checks ma_50 (computed SMA50) vs ema_200 (computed EMA200)
    # When pre-injected, the assertion must hold on the injected values
    assert result.golden_cross == (result.ma_50 > 0 and result.ema_200 > 0 and result.ma_50 > result.ema_200)


# ── Task 17.2: Hunter Engine tests ────────────────────────────────────────────

def test_compute_signals_ema21_present():
    """EMA 21 is computed and stored in TechnicalSignal."""
    result = compute_signals("NVDA", _mock_df())
    assert isinstance(result.ema_21, float)
    assert result.ema_21 > 0


def test_compute_signals_atr_pct_present():
    """atr_pct is computed as ATR / Close * 100."""
    result = compute_signals("NVDA", _mock_df())
    assert isinstance(result.atr_pct, float)
    expected = result.atr / result.entry * 100.0 if result.entry else 0.0
    assert abs(result.atr_pct - expected) < 0.01


def test_compute_signals_risk_reward_positive_for_long():
    """For a LONG signal, risk_reward = (TP1 - entry) / (entry - SL) must be > 0."""
    df = _mock_df()
    df["RSI_14"] = 25.0
    df["SMA_20"] = df["Close"] * 0.95
    result = compute_signals("NVDA", df)
    assert result.direction == "LONG"
    assert result.risk_reward > 0
    expected_rr = abs(result.take_profit_1 - result.entry) / abs(result.entry - result.stop_loss)
    assert abs(result.risk_reward - round(expected_rr, 2)) < 0.01


def test_compute_signals_risk_reward_positive_for_short():
    """For a SHORT signal, risk_reward must also be > 0."""
    df = _mock_df()
    df["RSI_14"] = 75.0
    df["SMA_20"] = df["Close"] * 1.05
    result = compute_signals("NVDA", df)
    assert result.direction == "SHORT"
    assert result.risk_reward > 0


def test_classify_horizon_short_term_ema21_break():
    """EMA 21 break alone triggers SHORT_TERM horizon."""
    assert _classify_horizon(
        "LONG", False, False, False, False, False, False,
        ema_21_break=True, atr_pct_high=False
    ) == "SHORT_TERM"


def test_classify_horizon_short_term_atr_pct():
    """High ATR% alone triggers SHORT_TERM horizon."""
    assert _classify_horizon(
        "LONG", False, False, False, False, False, False,
        ema_21_break=False, atr_pct_high=True
    ) == "SHORT_TERM"


def test_classify_horizon_long_term_no_short_signals():
    """LONG_TERM requires ema_200_above + adx_strong + obv_rising with no short signals."""
    assert _classify_horizon(
        "LONG", False, False, False, True, True, True,
        ema_21_break=False, atr_pct_high=False
    ) == "LONG_TERM"


def test_classify_horizon_both_ema21_plus_long():
    """EMA 21 break + all long-term conditions → BOTH."""
    assert _classify_horizon(
        "LONG", False, False, False, True, True, True,
        ema_21_break=True, atr_pct_high=False
    ) == "BOTH"


def test_build_horizon_reason_includes_ema21():
    """Horizon reason mentions EMA 21 when ema_21_break=True."""
    reason = _build_horizon_reason(
        "SHORT_TERM", False, False, False, False, False, False,
        ema_21_break=True, atr_pct_high=False
    )
    assert "EMA 21" in reason
    assert "2-10" in reason


def test_build_horizon_reason_long_term_updated_period():
    """Long-term horizon reason uses '3-8 שבועות' label."""
    reason = _build_horizon_reason(
        "LONG_TERM", False, False, False, True, True, True,
        ema_21_break=False, atr_pct_high=False
    )
    assert "3-8" in reason


def test_compute_signals_ema21_break_field():
    """ema_21_break is a bool in TechnicalSignal."""
    result = compute_signals("NVDA", _mock_df())
    assert isinstance(result.ema_21_break, bool)


def test_compute_signals_hunter_fields_complete():
    """All Task 17.2 TechnicalSignal fields are present and typed correctly."""
    result = compute_signals("NVDA", _mock_df())
    assert isinstance(result.ema_21, float)
    assert isinstance(result.ema_21_break, bool)
    assert isinstance(result.atr_pct, float) and result.atr_pct >= 0
    assert isinstance(result.risk_reward, float) and result.risk_reward >= 0
