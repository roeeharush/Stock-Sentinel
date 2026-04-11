import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone

from stock_sentinel.db import get_pending_alerts, update_outcome, get_daily_stats

log = logging.getLogger(__name__)

_MAX_AGE_DAYS = 5
_FETCH_PERIOD = f"{_MAX_AGE_DAYS + 3}d"


def _fetch_ohlcv(ticker: str) -> pd.DataFrame | None:
    """Fetch recent daily OHLCV. Returns None on failure."""
    try:
        df = yf.download(ticker, period=_FETCH_PERIOD, interval="1d", progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        return df
    except Exception as exc:
        log.warning("Validator: failed to fetch %s — %s", ticker, exc)
        return None


def _resolve_alert(alert: dict, df: pd.DataFrame) -> str | None:
    """Determine outcome for one alert against OHLCV data.

    Returns 'WIN', 'LOSS', 'EXPIRED', or None (not yet resolved).

    Logic (daily bars):
    - Get bars strictly AFTER the alert date (trade entered at next open).
    - For LONG: SL hit (Low <= stop_loss) = LOSS takes priority; else TP hit = WIN.
    - For SHORT: SL hit (High >= stop_loss) = LOSS takes priority; else TP hit = WIN.
    - If no bar resolves it within _MAX_AGE_DAYS: EXPIRED.
    - Conservative: if SL and TP both hit the same bar, LOSS wins.
    """
    alerted_at = datetime.fromisoformat(alert["alerted_at"])
    if alerted_at.tzinfo is None:
        alerted_at = alerted_at.replace(tzinfo=timezone.utc)
    alert_date = alerted_at.date()

    # Bars strictly after the alert date
    future = df[df.index.date > alert_date]

    age_days = (datetime.now(timezone.utc).date() - alert_date).days

    if future.empty:
        return "EXPIRED" if age_days >= _MAX_AGE_DAYS else None

    direction = alert["direction"]
    sl = float(alert["stop_loss"])
    tp = float(alert["take_profit"])

    for _, row in future.iterrows():
        high = float(row["High"])
        low = float(row["Low"])

        tp1 = alert.get("take_profit_1") or tp  # fall back to TP2 if not stored

        if direction == "LONG":
            if low <= sl:
                return "LOSS"
            if high >= tp1:
                return "WIN"
        else:  # SHORT
            if high >= sl:
                return "LOSS"
            if low <= tp1:
                return "WIN"

    # No bar resolved it yet
    return "EXPIRED" if age_days >= _MAX_AGE_DAYS else None


def validate_daily() -> dict:
    """Check all pending alerts against latest OHLCV. Update DB outcomes.

    Returns {"checked": N, "resolved": M}.
    """
    pending = get_pending_alerts(max_age_days=_MAX_AGE_DAYS)
    if not pending:
        log.info("Validator: no pending alerts")
        return {"checked": 0, "resolved": 0}

    # Fetch OHLCV per unique ticker (skip SYSTEM circuit-breaker alerts)
    tickers = list({a["ticker"] for a in pending if a["ticker"] != "SYSTEM"})
    price_data: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = _fetch_ohlcv(ticker)
        if df is not None:
            price_data[ticker] = df

    resolved = 0
    for alert in pending:
        ticker = alert["ticker"]
        if ticker == "SYSTEM":
            update_outcome(alert["id"], "EXPIRED")
            resolved += 1
            continue
        if ticker not in price_data:
            continue
        outcome = _resolve_alert(alert, price_data[ticker])
        if outcome is not None:
            update_outcome(alert["id"], outcome)
            resolved += 1
            log.info("Validator: %s %s → %s", ticker, alert["direction"], outcome)

    return {"checked": len(pending), "resolved": resolved}
