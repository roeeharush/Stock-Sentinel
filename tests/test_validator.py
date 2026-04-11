import pandas as pd
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from stock_sentinel import db as db_module
from stock_sentinel.validator import validate_daily, _resolve_alert, _fetch_ohlcv


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "_DB_PATH", tmp_path / "test.db")


def _make_df(highs, lows, base_date=None):
    """Build a minimal OHLCV DataFrame for testing _resolve_alert."""
    if base_date is None:
        base_date = datetime.now(timezone.utc).date()
    dates = pd.date_range(
        start=pd.Timestamp(base_date) + pd.Timedelta(days=1),
        periods=len(highs),
        freq="B",
        tz="UTC",
    )
    return pd.DataFrame(
        {
            "Open": [h - 1 for h in highs],
            "High": highs,
            "Low": lows,
            "Close": [h - 0.5 for h in highs],
            "Volume": [1_000_000] * len(highs),
        },
        index=dates,
    )


def _alert_dict(direction="LONG", entry=900.0, sl=882.0, tp=927.0, days_ago=1):
    alerted_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "id": 1,
        "ticker": "NVDA",
        "direction": direction,
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "rsi": 28.0,
        "technical_score": 75,
        "sentiment_score": 0.5,
        "confluence_factors": ["EMA 200 Trend"],
        "alerted_at": alerted_at.isoformat(),
        "outcome": None,
    }


# --- _resolve_alert unit tests ---

def test_long_win_tp_hit():
    alert = _alert_dict("LONG", sl=882.0, tp=927.0)
    df = _make_df(highs=[930.0], lows=[890.0])  # High >= TP, Low > SL
    assert _resolve_alert(alert, df) == "WIN"


def test_long_loss_sl_hit():
    alert = _alert_dict("LONG", sl=882.0, tp=927.0)
    df = _make_df(highs=[910.0], lows=[878.0])  # Low <= SL
    assert _resolve_alert(alert, df) == "LOSS"


def test_long_loss_when_both_hit_same_bar():
    """SL takes priority over TP when both hit on the same bar."""
    alert = _alert_dict("LONG", sl=882.0, tp=927.0)
    df = _make_df(highs=[930.0], lows=[880.0])  # both hit
    assert _resolve_alert(alert, df) == "LOSS"


def test_short_win_tp_hit():
    alert = _alert_dict("SHORT", sl=927.0, tp=882.0)
    df = _make_df(highs=[920.0], lows=[878.0])  # Low <= TP, High < SL
    assert _resolve_alert(alert, df) == "WIN"


def test_short_loss_sl_hit():
    alert = _alert_dict("SHORT", sl=927.0, tp=882.0)
    df = _make_df(highs=[930.0], lows=[885.0])  # High >= SL
    assert _resolve_alert(alert, df) == "LOSS"


def test_expired_when_no_resolution_and_old():
    alert = _alert_dict(days_ago=6)  # older than MAX_AGE_DAYS=5
    df = _make_df(highs=[905.0], lows=[895.0])  # neither TP nor SL hit
    assert _resolve_alert(alert, df) == "EXPIRED"


def test_none_when_no_resolution_and_recent():
    alert = _alert_dict(days_ago=1)
    df = _make_df(highs=[905.0], lows=[895.0])  # neither TP nor SL hit
    assert _resolve_alert(alert, df) is None


def test_none_when_no_future_bars_and_recent():
    """No bars after alert date and alert is recent → still pending."""
    alert = _alert_dict(days_ago=0)
    # Build empty df (no rows after today)
    df = pd.DataFrame(
        {"Open": [], "High": [], "Low": [], "Close": [], "Volume": []},
        index=pd.DatetimeIndex([], tz="UTC"),
    )
    assert _resolve_alert(alert, df) is None


# --- validate_daily integration tests ---

def test_validate_daily_no_pending_returns_zero():
    from stock_sentinel.db import init_db
    init_db()
    result = validate_daily()
    assert result == {"checked": 0, "resolved": 0}


def test_validate_daily_resolves_win(monkeypatch):
    from stock_sentinel.db import init_db, log_alert
    from stock_sentinel.models import Alert

    init_db()
    alert = Alert(
        ticker="NVDA", direction="LONG", entry=900.0,
        stop_loss=882.0, take_profit=927.0, rsi=28.0,
        sentiment_score=0.5, confluence_factors=["EMA 200 Trend"],
    )
    log_alert(alert, technical_score=75)

    # Mock yfinance to return a DF with High > TP
    mock_df = _make_df(highs=[935.0], lows=[890.0], base_date=(datetime.now(timezone.utc) - timedelta(days=1)).date())
    with patch("stock_sentinel.validator.yf.download", return_value=mock_df):
        result = validate_daily()

    assert result["resolved"] == 1
    pending = db_module.get_pending_alerts()
    assert len(pending) == 0  # resolved, no longer pending
