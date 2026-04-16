import asyncio
import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone

from stock_sentinel.db import get_active_trades, mark_tp_hit, mark_sl_hit
from stock_sentinel.notifier import send_trade_update  # noqa: E402  (needed for patch target)

log = logging.getLogger(__name__)


def _is_market_open() -> bool:
    """Return True when the NYSE is within regular trading hours (09:30–16:00 ET, Mon–Fri).

    Uses zoneinfo for correct DST handling.  Falls back to a UTC-4 approximation
    if zoneinfo is unavailable (Python < 3.9 environments).
    """
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        from datetime import timedelta
        offset = timedelta(hours=-4)          # EDT (UTC-4); close enough for a guard
        now_et = datetime.now(timezone.utc).astimezone(timezone(offset))

    if now_et.weekday() >= 5:                 # Saturday=5, Sunday=6
        return False
    market_open  = now_et.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now_et <= market_close


def _get_current_price(ticker: str) -> float | None:
    """Fetch the latest price for a ticker. Tries fast_info first, falls back to 1m bars."""
    try:
        info = yf.Ticker(ticker).fast_info
        price = getattr(info, "last_price", None)
        if price is not None and not (isinstance(price, float) and price != price):  # NaN guard
            return float(price)
    except Exception:
        pass
    try:
        df = yf.download(ticker, period="1d", interval="1m", progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        return float(df["Close"].iloc[-1])
    except Exception as exc:
        log.warning("Monitor: price fetch failed for %s — %s", ticker, exc)
        return None


def _check_levels(trade: dict, current_price: float) -> list[str]:
    """Return newly-triggered level names for this trade at current_price.

    For LONG: SL hit if price <= stop_loss (checked first).
              TP1/TP2/TP3 hit if price >= respective target and not yet marked.
    For SHORT: SL hit if price >= stop_loss.
               TP1/TP2/TP3 hit if price <= respective target and not yet marked.

    SL takes full priority — if SL is returned, no TPs are included.
    Results are ordered TP1 → TP2 → TP3 so notifications fire in sequence.
    """
    direction = trade["direction"]
    sl  = trade["stop_loss"]
    tp  = trade["take_profit"]       # TP2
    tp1 = trade.get("take_profit_1") or tp
    tp3 = trade.get("take_profit_3") or tp

    updates: list[str] = []

    if direction == "LONG":
        if current_price <= sl:
            return ["SL"]
        if not trade.get("tp1_hit") and current_price >= tp1:
            updates.append("TP1")
        if not trade.get("tp2_hit") and current_price >= tp:
            updates.append("TP2")
        if not trade.get("tp3_hit") and current_price >= tp3:
            updates.append("TP3")

    elif direction == "SHORT":
        if current_price >= sl:
            return ["SL"]
        if not trade.get("tp1_hit") and current_price <= tp1:
            updates.append("TP1")
        if not trade.get("tp2_hit") and current_price <= tp:
            updates.append("TP2")
        if not trade.get("tp3_hit") and current_price <= tp3:
            updates.append("TP3")

    return updates


async def check_active_trades(bot_token: str, chat_id: str) -> dict:
    """Check all open trades against live prices and send threaded Telegram updates.

    Returns {"checked": N, "updates_sent": M}.
    """
    log.info("Monitor process started. Checking market status...")

    if not _is_market_open():
        log.info("Market is currently closed (NY Time). Skipping scan.")
        return {"checked": 0, "updates_sent": 0}

    log.info("Market is open. Fetching active trades from DB...")

    trades = get_active_trades()
    if not trades:
        log.info("Monitor: no active trades in DB — nothing to check.")
        return {"checked": 0, "updates_sent": 0}

    log.info("Monitor: %d active trade(s) found. Fetching live prices...", len(trades))

    # Batch price fetch — one ticker at a time (yfinance free tier)
    tickers = list({t["ticker"] for t in trades})
    current_prices: dict[str, float] = {}
    for ticker in tickers:
        log.info("Checking trade potential for %s...", ticker)
        price = _get_current_price(ticker)
        if price is not None:
            current_prices[ticker] = price
            log.info("Monitor: %s current price = $%.2f", ticker, price)
        else:
            log.warning("Monitor: could not fetch price for %s — skipping", ticker)

    updates_sent = 0
    for trade in trades:
        ticker = trade["ticker"]
        if ticker not in current_prices:
            continue

        price = current_prices[ticker]
        triggered = _check_levels(trade, price)

        if not triggered:
            log.debug("Monitor: %s — no levels triggered at $%.2f", ticker, price)

        for update_type in triggered:
            success = await send_trade_update(trade, update_type, price, bot_token, chat_id)
            if success:
                if update_type == "SL":
                    mark_sl_hit(trade["id"])
                else:
                    tp_num = int(update_type[2])   # "TP1" → 1, "TP2" → 2, "TP3" → 3
                    mark_tp_hit(trade["id"], tp_num)
                updates_sent += 1
                log.info("Monitor: %s %s hit at %.2f", ticker, update_type, price)

    log.info("Monitor cycle complete: checked=%d updates_sent=%d", len(trades), updates_sent)
    return {"checked": len(trades), "updates_sent": updates_sent}
