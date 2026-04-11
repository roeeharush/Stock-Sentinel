import asyncio
import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone

from stock_sentinel.db import get_active_trades, mark_tp_hit, mark_sl_hit
from stock_sentinel.notifier import send_trade_update  # noqa: E402  (needed for patch target)

log = logging.getLogger(__name__)


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
    trades = get_active_trades()
    if not trades:
        log.debug("Monitor: no active trades")
        return {"checked": 0, "updates_sent": 0}

    # Batch price fetch — one ticker at a time (yfinance free tier)
    tickers = list({t["ticker"] for t in trades})
    current_prices: dict[str, float] = {}
    for ticker in tickers:
        price = _get_current_price(ticker)
        if price is not None:
            current_prices[ticker] = price

    updates_sent = 0
    for trade in trades:
        ticker = trade["ticker"]
        if ticker not in current_prices:
            continue

        price = current_prices[ticker]
        triggered = _check_levels(trade, price)

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

    return {"checked": len(trades), "updates_sent": updates_sent}
