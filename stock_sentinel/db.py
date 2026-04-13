import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from stock_sentinel.models import Alert

_DB_PATH = Path(__file__).parent.parent / "data" / "sentinel.db"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                take_profit_1 REAL DEFAULT NULL,
                take_profit_2 REAL DEFAULT NULL,
                take_profit_3 REAL DEFAULT NULL,
                rsi REAL NOT NULL,
                technical_score INTEGER NOT NULL DEFAULT 0,
                sentiment_score REAL NOT NULL DEFAULT 0.0,
                confluence_factors TEXT NOT NULL DEFAULT '[]',
                horizon TEXT DEFAULT '',
                alerted_at TEXT NOT NULL,
                outcome TEXT DEFAULT NULL,
                validated_at TEXT DEFAULT NULL,
                telegram_message_id INTEGER DEFAULT NULL,
                tp1_hit INTEGER NOT NULL DEFAULT 0,
                tp2_hit INTEGER NOT NULL DEFAULT 0,
                tp3_hit INTEGER NOT NULL DEFAULT 0,
                sl_hit  INTEGER NOT NULL DEFAULT 0
            )
        """)
        # --- forward-compatible migrations ---
        for col, typedef in [
            ("take_profit_1",       "REAL DEFAULT NULL"),
            ("take_profit_2",       "REAL DEFAULT NULL"),
            ("take_profit_3",       "REAL DEFAULT NULL"),
            ("horizon",             "TEXT DEFAULT ''"),
            ("telegram_message_id", "INTEGER DEFAULT NULL"),
            ("tp1_hit",             "INTEGER NOT NULL DEFAULT 0"),
            ("tp2_hit",             "INTEGER NOT NULL DEFAULT 0"),
            ("tp3_hit",             "INTEGER NOT NULL DEFAULT 0"),
            ("sl_hit",              "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE alerts ADD COLUMN {col} {typedef}")
            except Exception:
                pass  # column already exists


def log_alert(alert: Alert, technical_score: int = 0, telegram_message_id: int | None = None) -> int:
    """Insert a sent alert into the DB. Returns the new row id."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO alerts
               (ticker, direction, entry_price, stop_loss, take_profit,
                take_profit_1, take_profit_2, take_profit_3,
                rsi, technical_score, sentiment_score,
                confluence_factors, horizon, telegram_message_id, alerted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                alert.ticker,
                alert.direction,
                alert.entry,
                alert.stop_loss,
                alert.take_profit,
                alert.take_profit_1,
                alert.take_profit,
                alert.take_profit_3,
                alert.rsi,
                technical_score,
                alert.sentiment_score,
                json.dumps(alert.confluence_factors),
                alert.horizon,
                telegram_message_id,
                alert.generated_at.isoformat(),
            ),
        )
        return cur.lastrowid


def update_outcome(alert_id: int, outcome: str) -> None:
    """Set outcome ('WIN', 'LOSS', 'EXPIRED') for an alert row."""
    with _connect() as conn:
        conn.execute(
            "UPDATE alerts SET outcome=?, validated_at=? WHERE id=?",
            (outcome, datetime.now(timezone.utc).isoformat(), alert_id),
        )


def get_pending_alerts(max_age_days: int = 5) -> list[dict]:
    """Return unresolved alerts within max_age_days old."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE outcome IS NULL ORDER BY alerted_at DESC"
        ).fetchall()
    result = []
    now = datetime.now(timezone.utc)
    for row in rows:
        d = dict(row)
        d["confluence_factors"] = json.loads(d["confluence_factors"])
        alerted_at = datetime.fromisoformat(d["alerted_at"])
        if alerted_at.tzinfo is None:
            alerted_at = alerted_at.replace(tzinfo=timezone.utc)
        if (now - alerted_at).days <= max_age_days:
            result.append(d)
    return result


def get_daily_stats() -> dict:
    """Return today's resolved alerts: total, wins, losses, win_rate, top_factors."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE validated_at LIKE ? AND outcome IN ('WIN','LOSS')",
            (f"{today}%",),
        ).fetchall()

    total = len(rows)
    if total == 0:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "top_factors": []}

    wins = sum(1 for r in rows if r["outcome"] == "WIN")

    factor_wins: dict[str, int] = {}
    factor_total: dict[str, int] = {}
    for row in rows:
        factors = json.loads(row["confluence_factors"])
        for f in factors:
            factor_total[f] = factor_total.get(f, 0) + 1
            if row["outcome"] == "WIN":
                factor_wins[f] = factor_wins.get(f, 0) + 1

    top_factors = sorted(
        factor_total.keys(),
        key=lambda f: (factor_wins.get(f, 0) / factor_total[f], factor_total[f]),
        reverse=True,
    )[:5]

    return {
        "total": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": wins / total,
        "top_factors": top_factors,
    }


def get_active_trades(max_age_days: int = 5) -> list[dict]:
    """Return alerts still being monitored: outcome IS NULL, SL not hit, TP3 not hit."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM alerts
               WHERE outcome IS NULL
                 AND sl_hit  = 0
                 AND tp3_hit = 0
                 AND ticker != 'SYSTEM'
               ORDER BY alerted_at DESC"""
        ).fetchall()
    now = datetime.now(timezone.utc)
    result = []
    for row in rows:
        d = dict(row)
        d["confluence_factors"] = json.loads(d.get("confluence_factors", "[]"))
        alerted_at = datetime.fromisoformat(d["alerted_at"])
        if alerted_at.tzinfo is None:
            alerted_at = alerted_at.replace(tzinfo=timezone.utc)
        if (now - alerted_at).days <= max_age_days:
            result.append(d)
    return result


def mark_tp_hit(alert_id: int, tp_num: int) -> None:
    """Mark TP1, TP2, or TP3 as hit. tp_num must be 1, 2, or 3."""
    col = f"tp{tp_num}_hit"
    with _connect() as conn:
        conn.execute(f"UPDATE alerts SET {col} = 1 WHERE id = ?", (alert_id,))


def mark_sl_hit(alert_id: int) -> None:
    """Mark SL as hit (trade closed at loss)."""
    with _connect() as conn:
        conn.execute("UPDATE alerts SET sl_hit = 1 WHERE id = ?", (alert_id,))


def get_today_alerts() -> list[dict]:
    """Return all trade alerts sent today (UTC date), resolved or still open.

    Used by the daily performance report to build the prediction-vs-actual table.
    Excludes SYSTEM diagnostic rows.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM alerts
               WHERE alerted_at LIKE ? AND ticker != 'SYSTEM'
               ORDER BY alerted_at DESC""",
            (f"{today}%",),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["confluence_factors"] = json.loads(d.get("confluence_factors", "[]"))
        except Exception:
            d["confluence_factors"] = []
        result.append(d)
    return result


def get_weekly_trades(days: int = 7) -> list[dict]:
    """Return all trades alerted within the past *days* days, with decoded factors.

    Includes both resolved and unresolved trades so the learning engine can
    report on unresolved count separately.
    """
    cutoff = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    from datetime import timedelta
    cutoff -= timedelta(days=days)
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM alerts
               WHERE alerted_at >= ?
                 AND ticker != 'SYSTEM'
               ORDER BY alerted_at ASC""",
            (cutoff.isoformat(),),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["confluence_factors"] = json.loads(d.get("confluence_factors", "[]"))
        except Exception:
            d["confluence_factors"] = []
        result.append(d)
    return result
