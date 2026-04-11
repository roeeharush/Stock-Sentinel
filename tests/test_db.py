import json
import pytest
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch
from stock_sentinel.models import Alert
from stock_sentinel import db as db_module
from stock_sentinel.db import init_db, log_alert, update_outcome, get_pending_alerts, get_daily_stats, get_active_trades, mark_tp_hit, mark_sl_hit


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Point DB at a temp file for each test."""
    tmp_db = tmp_path / "test_sentinel.db"
    monkeypatch.setattr(db_module, "_DB_PATH", tmp_db)


def _alert(ticker="NVDA", direction="LONG", technical_score=75):
    return Alert(
        ticker=ticker,
        direction=direction,
        entry=900.0,
        stop_loss=882.0,
        take_profit=927.0,
        rsi=28.0,
        sentiment_score=0.50,
        confluence_factors=["EMA 200 Trend", "Volume Spike"],
    ), technical_score


def test_init_db_creates_table():
    init_db()
    with db_module._connect() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert any(t["name"] == "alerts" for t in tables)


def test_log_alert_returns_id():
    init_db()
    alert, ts = _alert()
    row_id = log_alert(alert, ts)
    assert isinstance(row_id, int)
    assert row_id >= 1


def test_log_alert_stores_fields():
    init_db()
    alert, ts = _alert()
    row_id = log_alert(alert, ts)
    with db_module._connect() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id=?", (row_id,)).fetchone()
    assert row["ticker"] == "NVDA"
    assert row["direction"] == "LONG"
    assert abs(row["entry_price"] - 900.0) < 0.01
    assert row["technical_score"] == 75
    assert json.loads(row["confluence_factors"]) == ["EMA 200 Trend", "Volume Spike"]
    assert row["outcome"] is None


def test_update_outcome_sets_win():
    init_db()
    alert, ts = _alert()
    row_id = log_alert(alert, ts)
    update_outcome(row_id, "WIN")
    with db_module._connect() as conn:
        row = conn.execute("SELECT outcome FROM alerts WHERE id=?", (row_id,)).fetchone()
    assert row["outcome"] == "WIN"


def test_get_pending_alerts_returns_unresolved():
    init_db()
    alert, ts = _alert()
    log_alert(alert, ts)
    pending = get_pending_alerts()
    assert len(pending) == 1
    assert pending[0]["ticker"] == "NVDA"
    assert pending[0]["outcome"] is None


def test_get_pending_alerts_excludes_resolved():
    init_db()
    alert, ts = _alert()
    row_id = log_alert(alert, ts)
    update_outcome(row_id, "WIN")
    pending = get_pending_alerts()
    assert len(pending) == 0


def test_get_daily_stats_empty():
    init_db()
    stats = get_daily_stats()
    assert stats["total"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["top_factors"] == []


def test_get_daily_stats_with_outcomes():
    init_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    # Insert two WIN rows and one LOSS row validated today
    with db_module._connect() as conn:
        for outcome, factors in [
            ("WIN", '["EMA 200 Trend","Volume Spike"]'),
            ("WIN", '["EMA 200 Trend","MACD Bullish"]'),
            ("LOSS", '["Volume Spike"]'),
        ]:
            conn.execute(
                """INSERT INTO alerts
                   (ticker, direction, entry_price, stop_loss, take_profit, rsi,
                    confluence_factors, alerted_at, outcome, validated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                ("NVDA", "LONG", 900, 882, 927, 28, factors, now_iso, outcome, now_iso),
            )
    stats = get_daily_stats()
    assert stats["total"] == 3
    assert stats["wins"] == 2
    assert stats["losses"] == 1
    assert abs(stats["win_rate"] - 2/3) < 0.001
    # EMA 200 Trend appears in both WINs → should be top factor
    assert "EMA 200 Trend" in stats["top_factors"]


def test_log_alert_stores_telegram_message_id():
    init_db()
    alert, ts = _alert()
    row_id = log_alert(alert, ts, telegram_message_id=999)
    with db_module._connect() as conn:
        row = conn.execute("SELECT telegram_message_id FROM alerts WHERE id=?", (row_id,)).fetchone()
    assert row["telegram_message_id"] == 999


def test_get_active_trades_returns_open():
    init_db()
    alert, ts = _alert()
    log_alert(alert, ts)
    trades = get_active_trades()
    assert len(trades) == 1
    assert trades[0]["ticker"] == "NVDA"
    assert trades[0]["sl_hit"] == 0


def test_get_active_trades_excludes_sl_hit():
    init_db()
    alert, ts = _alert()
    row_id = log_alert(alert, ts)
    mark_sl_hit(row_id)
    assert get_active_trades() == []


def test_get_active_trades_excludes_tp3_hit():
    init_db()
    alert, ts = _alert()
    row_id = log_alert(alert, ts)
    mark_tp_hit(row_id, 3)
    assert get_active_trades() == []


def test_mark_tp_hit_sets_column():
    init_db()
    alert, ts = _alert()
    row_id = log_alert(alert, ts)
    mark_tp_hit(row_id, 1)
    with db_module._connect() as conn:
        row = conn.execute("SELECT tp1_hit FROM alerts WHERE id=?", (row_id,)).fetchone()
    assert row["tp1_hit"] == 1


def test_mark_sl_hit_sets_column():
    init_db()
    alert, ts = _alert()
    row_id = log_alert(alert, ts)
    mark_sl_hit(row_id)
    with db_module._connect() as conn:
        row = conn.execute("SELECT sl_hit FROM alerts WHERE id=?", (row_id,)).fetchone()
    assert row["sl_hit"] == 1
