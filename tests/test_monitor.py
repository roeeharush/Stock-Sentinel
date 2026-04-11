import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from stock_sentinel import db as db_module
from stock_sentinel.monitor import _check_levels, _get_current_price, check_active_trades


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "_DB_PATH", tmp_path / "test.db")


def _trade(direction="LONG", entry=900.0, sl=882.0, tp=927.0, tp1=913.5, tp3=945.0,
           tp1_hit=0, tp2_hit=0, tp3_hit=0, sl_hit=0, telegram_message_id=None):
    alerted_at = datetime.now(timezone.utc) - timedelta(hours=2)
    return {
        "id": 1,
        "ticker": "NVDA",
        "direction": direction,
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "take_profit_1": tp1,
        "take_profit_3": tp3,
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        "tp3_hit": tp3_hit,
        "sl_hit": sl_hit,
        "telegram_message_id": telegram_message_id,
        "alerted_at": alerted_at.isoformat(),
        "confluence_factors": [],
    }


# --- _check_levels unit tests ---

def test_long_sl_hit():
    assert _check_levels(_trade("LONG"), 880.0) == ["SL"]


def test_long_tp1_hit():
    assert _check_levels(_trade("LONG"), 914.0) == ["TP1"]


def test_long_tp1_and_tp2_hit_together():
    result = _check_levels(_trade("LONG"), 928.0)
    assert "TP1" in result
    assert "TP2" in result
    assert "SL" not in result


def test_long_all_three_tps():
    result = _check_levels(_trade("LONG"), 950.0)
    assert result == ["TP1", "TP2", "TP3"]


def test_long_sl_takes_priority_over_tp():
    """Even if price is somehow above TP, if it's also below SL, SL wins."""
    # Edge case: price below SL — SL returned, no TPs
    assert _check_levels(_trade("LONG"), 880.0) == ["SL"]


def test_long_no_levels_hit():
    assert _check_levels(_trade("LONG"), 910.0) == []


def test_short_sl_hit():
    # SHORT: sl=927, price above sl
    assert _check_levels(_trade("SHORT", sl=927.0, tp=882.0, tp1=895.5, tp3=855.0), 930.0) == ["SL"]


def test_short_tp1_hit():
    result = _check_levels(_trade("SHORT", sl=927.0, tp=882.0, tp1=895.5, tp3=855.0), 894.0)
    assert "TP1" in result
    assert "SL" not in result


def test_already_hit_tp1_not_duplicated():
    """tp1_hit=1 means TP1 notification already sent — must not send again."""
    trade = _trade("LONG", tp1_hit=1)
    result = _check_levels(trade, 928.0)
    assert "TP1" not in result
    assert "TP2" in result


# --- check_active_trades integration tests ---

@pytest.mark.asyncio
async def test_check_active_trades_no_trades():
    from stock_sentinel.db import init_db
    init_db()
    result = await check_active_trades("fake_token", "fake_chat")
    assert result == {"checked": 0, "updates_sent": 0}


@pytest.mark.asyncio
async def test_check_active_trades_sends_tp1_update():
    from stock_sentinel.db import init_db, log_alert
    from stock_sentinel.models import Alert

    init_db()
    alert = Alert(
        ticker="NVDA", direction="LONG", entry=900.0,
        stop_loss=882.0, take_profit=927.0,
        take_profit_1=913.5, take_profit_3=945.0,
        rsi=28.0, sentiment_score=0.5,
    )
    row_id = log_alert(alert, technical_score=75, telegram_message_id=100)

    with (
        patch("stock_sentinel.monitor._get_current_price", return_value=920.0),
        patch("stock_sentinel.monitor.send_trade_update",
              new_callable=AsyncMock, return_value=True) as mock_update,
    ):
        result = await check_active_trades("fake_token", "fake_chat")

    assert result["updates_sent"] >= 1
    # TP1 was triggered (price 920 >= tp1 913.5)
    calls = [c.args[1] for c in mock_update.call_args_list]
    assert "TP1" in calls


@pytest.mark.asyncio
async def test_check_active_trades_marks_sl_in_db():
    from stock_sentinel.db import init_db, log_alert, get_active_trades
    from stock_sentinel.models import Alert

    init_db()
    alert = Alert(
        ticker="NVDA", direction="LONG", entry=900.0,
        stop_loss=882.0, take_profit=927.0,
        take_profit_1=913.5, take_profit_3=945.0,
        rsi=28.0, sentiment_score=0.5,
    )
    log_alert(alert, technical_score=75)

    with (
        patch("stock_sentinel.monitor._get_current_price", return_value=878.0),  # below SL
        patch("stock_sentinel.monitor.send_trade_update",
              new_callable=AsyncMock, return_value=True),
    ):
        await check_active_trades("fake_token", "fake_chat")

    # Trade should now have sl_hit=1 and be excluded from active trades
    assert get_active_trades() == []
