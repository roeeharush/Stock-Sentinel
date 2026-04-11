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
                validated_at TEXT DEFAULT NULL
            )
        """)
        # --- forward-compatible migrations ---
        for col, typedef in [
            ("take_profit_1", "REAL DEFAULT NULL"),
            ("take_profit_2", "REAL DEFAULT NULL"),
            ("take_profit_3", "REAL DEFAULT NULL"),
            ("horizon",       "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE alerts ADD COLUMN {col} {typedef}")
            except Exception:
                pass  # column already exists


def log_alert(alert: Alert, technical_score: int = 0) -> int:
    """Insert a sent alert into the DB. Returns the new row id."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO alerts
               (ticker, direction, entry_price, stop_loss, take_profit,
                take_profit_1, take_profit_2, take_profit_3,
                rsi, technical_score, sentiment_score,
                confluence_factors, horizon, alerted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                alert.ticker,
                alert.direction,
                alert.entry,
                alert.stop_loss,
                alert.take_profit,          # TP2
                alert.take_profit_1,
                alert.take_profit,          # TP2 stored in both take_profit and take_profit_2
                alert.take_profit_3,
                alert.rsi,
                technical_score,
                alert.sentiment_score,
                json.dumps(alert.confluence_factors),
                alert.horizon,
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
