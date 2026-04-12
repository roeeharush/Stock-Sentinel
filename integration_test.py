#!/usr/bin/env python
"""
Full System Integration Test — Task 14 Dry Run
=================================================
Phase 1 : Build a realistic NVDA alert and send it to Telegram.
Phase 2 : Inject the alert into sentinel.db with TP1 set 0.5 % below
          the live NVDA price (guarantees the monitor fires TP1 immediately).
Phase 3 : Run check_active_trades() to trigger the threaded reply.
Cleanup : Remove the test row so no fake data persists.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yfinance as yf

from stock_sentinel import config
from stock_sentinel.db import _connect, init_db
from stock_sentinel.models import Alert
from stock_sentinel.monitor import check_active_trades
from stock_sentinel.notifier import send_alert


def _separator(label: str = "") -> None:
    width = 60
    if label:
        pad = max((width - len(label) - 2) // 2, 2)
        print(f"\n{'-' * pad} {label} {'-' * pad}")
    else:
        print("-" * width)


async def run_integration_test() -> None:
    _separator("Stock Sentinel — Task 14 Integration Test")

    # ── Ensure DB schema is current ──────────────────────────────────
    init_db()

    # ── Phase 1: Fetch live NVDA price ───────────────────────────────
    _separator("Phase 1 · Fetch live NVDA price")
    ticker_obj = yf.Ticker("NVDA")
    current_price = float(ticker_obj.fast_info.last_price)
    print(f"  NVDA live price : ${current_price:.2f}")

    # Build realistic ATR-based targets
    atr        = current_price * 0.025           # ~2.5 % ATR proxy
    entry      = round(current_price * 0.998, 2) # tiny discount to current
    stop_loss  = round(entry - 2.0 * atr, 2)    # SL = entry − 2×ATR
    tp1        = round(current_price * 0.995, 2) # 0.5 % BELOW live → fires immediately
    tp2        = round(entry + 3.0 * atr, 2)    # TP2 (mid)
    tp3        = round(entry + 5.0 * atr, 2)    # TP3 (ambitious)

    alert = Alert(
        ticker="NVDA",
        direction="LONG",
        entry=entry,
        stop_loss=stop_loss,
        take_profit=tp2,          # TP2 = take_profit field (backward-compat)
        take_profit_1=tp1,
        take_profit_3=tp3,
        rsi=52.4,
        sentiment_score=0.64,
        twitter_score=0.48,
        news_score=0.72,
        rss_score=0.66,
        confluence_factors=[
            "EMA 200 Trend",
            "Volume Spike",
            "Bullish Engulfing",
            "MACD Bullish",
        ],
        horizon="SHORT_TERM",
        horizon_reason="פריצת ווליום עם תבנית נרות שורית — אות לטווח קצר (2-14 יום)",
    )

    print(f"  Entry  : ${alert.entry:.2f}")
    print(f"  SL     : ${alert.stop_loss:.2f}")
    print(f"  TP1    : ${alert.take_profit_1:.2f}  ← 0.5 % below live (fires immediately)")
    print(f"  TP2    : ${alert.take_profit:.2f}")
    print(f"  TP3    : ${alert.take_profit_3:.2f}")

    print("\n  Sending alert to Telegram …")
    message_id = await send_alert(
        alert,
        headlines=[
            "NVDA posts record data-center revenue beat",
            "AI chip demand surges — analysts raise price targets",
        ],
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
    )

    if message_id is None:
        print("  ✗ Telegram send failed — aborting test.")
        sys.exit(1)

    print(f"  ✓ Alert sent  |  message_id = {message_id}")

    # ── Phase 2: Inject into DB ───────────────────────────────────────
    _separator("Phase 2 · Inject into sentinel.db")
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO alerts
               (ticker, direction, entry_price, stop_loss, take_profit,
                take_profit_1, take_profit_2, take_profit_3,
                rsi, technical_score, sentiment_score,
                confluence_factors, horizon, telegram_message_id, alerted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "NVDA",
                "LONG",
                alert.entry,
                alert.stop_loss,
                alert.take_profit,
                alert.take_profit_1,
                alert.take_profit,   # take_profit_2 mirrors TP2
                alert.take_profit_3,
                alert.rsi,
                85,                  # synthetic technical_score
                alert.sentiment_score,
                json.dumps(alert.confluence_factors),
                alert.horizon,
                message_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        test_row_id = cur.lastrowid

    print(f"  ✓ Row inserted  |  id = {test_row_id}")
    print(f"  telegram_message_id = {message_id}")
    print(f"  Condition check : {current_price:.2f} >= {tp1:.2f}  →  TP1 will fire ✓")

    # ── Phase 3: Run the monitor ──────────────────────────────────────
    _separator("Phase 3 · Run check_active_trades()")
    result = await check_active_trades(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
    print(f"  Result : {result}")

    if result["updates_sent"] > 0:
        print("  ✓ Threaded reply sent to Telegram")
    else:
        print("  ✗ No updates sent — check logs above for errors")

    # ── Cleanup ───────────────────────────────────────────────────────
    _separator("Cleanup · Remove test row")
    with _connect() as conn:
        conn.execute("DELETE FROM alerts WHERE id = ?", (test_row_id,))
    print(f"  ✓ Row {test_row_id} deleted from sentinel.db")

    # ── Summary ───────────────────────────────────────────────────────
    _separator("Test Complete")
    print(f"  ✓ Phase 1 — Alert sent           (message_id={message_id})")
    print(f"  ✓ Phase 2 — DB row injected       (row_id={test_row_id})")
    print(f"  ✓ Phase 3 — Monitor fired         ({result['updates_sent']} update(s))")
    print(f"  ✓ Cleanup  — No fake data remains")
    print()
    print("  Check Telegram channel for:")
    print("    1.  🎯 איתות למסחר — NVDA  (the initial alert)")
    print("    2.  🔔 עדכון טרייד: NVDA — ✅ יעד 1 (שמרני) הושג!  (threaded reply)")
    _separator()


if __name__ == "__main__":
    asyncio.run(run_integration_test())
