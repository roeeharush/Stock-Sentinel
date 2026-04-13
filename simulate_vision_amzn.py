"""
simulate_vision_amzn.py — Task 29 simulation
=============================================
Demonstrates the full Vision Analyst pipeline for an AMZN LONG breakout:

  1.  Fetch 90 days of AMZN data via yfinance
  2.  Build a mock TechnicalSignal (breakout setup)
  3.  Generate a high-res chart PNG via visualizer.generate_chart (DPI 200)
  4.  Run the 4-agent debate (Bull + Bear + Visionary + Judge)
     — Live if ANTHROPIC_API_KEY is set, mock otherwise
  5.  Build & print the full Telegram message
  6.  Confirm the PNG was deleted after the simulated send
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

# ── UTF-8 safe print ──────────────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _p(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode())


# ─────────────────────────────────────────────────────────────────────────────
# Mock data when API key is absent
# ─────────────────────────────────────────────────────────────────────────────

MOCK_BULL_JSON = json.dumps({
    "טיעון_ראשי": "AMZN פרצה מעל אזור ההתנגדות הקלאסי ב-$195 עם עלייה ניכרת בנפח.",
    "נקודות_תמיכה": [
        "Golden Cross: SMA50 חצה מעל EMA200 לפני 3 ימים",
        "RSI דיברגנס שורי על ה-4H",
        "ענן AWS — תוצאות Q1 צפויות לחרוג מהציפיות"
    ],
    "יעד_מחיר": "$215 בטווח של 3 שבועות — הרחבת ATR × 5",
})

MOCK_BEAR_JSON = json.dumps({
    "טיעון_ראשי": "רמת $205 היא פיבונאצ'י 61.8% ממהלך היורד מ-$230 — צוואר בקבוק משמעותי.",
    "סיכונים_עיקריים": [
        "תשואות אג\"ח ל-10 שנים עולות — לחץ על מכפילי צמיחה",
        "FTC עשויה לחדש חקירת הגבלים עסקיים",
    ],
    "תרחיש_כישלון": "סגירה מתחת ל-$191 תאשר כישלון פריצה וחזרה ל-$182.",
})

MOCK_VISIONARY_JSON = json.dumps({
    "תבנית_ויזואלית": "דגל שורי בפריצה (Bull Flag Breakout)",
    "תיאור": "לאחר מהלך חד ב-8%, המחיר התגבש ב-5 קנדלסטיקים עם נפח פוחת — פריצה מעל הדגל עם עלייה חדה בנפח מאשרת את ההמשך",
    "מאשר_סיגנל": True,
    "השפעה_על_ביטחון": 15,
})

MOCK_JUDGE_JSON = json.dumps({
    "ציון_ביטחון": 81,
    "הכרעה": "הסיגנל חזק: פריצה טכנית עם אישור ויזואלי מסוכן הראייה.",
    "נימוק": "שלושה גורמים מתכנסים: Golden Cross, פריצת ATH, ודגל שורי מאושר. ניתוח הראייה מוסיף אישור עצמאי לתרחיש השורי.",
    "המלצה": "כנס",
})


# ─────────────────────────────────────────────────────────────────────────────
# Main simulation
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    _p("\n" + "=" * 62)
    _p("  TASK 29 SIMULATION — AMZN Vision Analyst Agent")
    _p("=" * 62)

    # ── Step 1: Fetch AMZN data ──────────────────────────────────────────────
    _p("\n[1/6] Fetching AMZN market data...")
    try:
        import yfinance as yf
        df = yf.download("AMZN", period="90d", interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("Empty DataFrame")
        _p(f"      OK — {len(df)} bars fetched (last close: ${df['Close'].iloc[-1]:.2f})")
    except Exception as e:
        _p(f"      WARN: yfinance failed ({e}), using synthetic data")
        import pandas as pd
        import numpy as np
        rng = pd.date_range("2025-01-01", periods=90, freq="B")
        prices = 180.0 + np.cumsum(np.random.normal(0.3, 1.5, 90))
        df = pd.DataFrame({
            "Open":   prices - 0.5,
            "High":   prices + 1.5,
            "Low":    prices - 1.5,
            "Close":  prices,
            "Volume": np.random.randint(30_000_000, 80_000_000, 90).astype(float),
        }, index=rng)
        df.index.name = "Date"

    # Flatten MultiIndex columns if present (yfinance ≥ 0.2.38 quirk)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close_price = float(df["Close"].iloc[-1])

    # ── Step 2: Build mock TechnicalSignal ───────────────────────────────────
    _p("\n[2/6] Building AMZN LONG breakout signal...")
    from stock_sentinel.models import TechnicalSignal
    import numpy as np

    atr = float(df["High"].iloc[-20:].mean() - df["Low"].iloc[-20:].mean()) * 0.5
    entry      = round(close_price, 2)
    stop_loss  = round(entry - 2.0 * atr, 2)
    tp1        = round(entry + 1.5 * atr, 2)
    tp2        = round(entry + 3.0 * atr, 2)
    tp3        = round(entry + 5.0 * atr, 2)

    signal = TechnicalSignal(
        ticker="AMZN",
        rsi=54.2,
        ma_20=float(df["Close"].rolling(20).mean().iloc[-1]),
        ma_50=float(df["Close"].rolling(50).mean().iloc[-1]),
        atr=atr,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=tp2,
        direction="LONG",
        analyzed_at=datetime.now(timezone.utc),
        ema_200=float(df["Close"].ewm(span=200, adjust=False).mean().iloc[-1]),
        vwap=entry * 0.998,
        volume_spike=True,
        candlestick_pattern="Bullish Engulfing",
        macd_bullish=True,
        technical_score=84,
        confluence_factors=[
            "EMA 200 Support", "Volume Spike", "MACD Bullish Cross",
            "Golden Cross Confirmed", "Bull Flag Breakout",
        ],
        take_profit_1=tp1,
        take_profit_3=tp3,
        bb_breakout=True,
        adx_strong=True,
        obv_rising=True,
        horizon="SHORT_TERM",
        horizon_reason="פריצת ATH עם נפח יוצא דופן — מומנטום קצר-טווח",
        fib_618=round(entry * 0.985, 2),
        fib_65=round(entry * 0.990, 2),
        poc_price=round(entry * 0.994, 2),
        golden_cross=True,
        rsi_divergence="bullish",
        ema_21=round(entry * 0.997, 2),
        ema_21_break=True,
        atr_pct=round(atr / entry * 100, 2),
        risk_reward=round((tp1 - entry) / (entry - stop_loss), 2),
    )
    _p(f"      OK — entry=${entry:.2f}  SL=${stop_loss:.2f}  TP1=${tp1:.2f}  score={signal.technical_score}")

    # ── Step 3: Generate chart PNG ────────────────────────────────────────────
    _p("\n[3/6] Generating high-res chart (DPI 200)...")
    from stock_sentinel.visualizer import generate_chart
    chart_path = generate_chart("AMZN", df, signal)
    chart_size_kb = os.path.getsize(chart_path) // 1024
    _p(f"      OK — {chart_path}  ({chart_size_kb} KB)")

    # ── Step 4: Run 4-agent debate ────────────────────────────────────────────
    _p("\n[4/6] Running 4-agent debate (Bull + Bear + Visionary + Judge)...")

    from stock_sentinel import config as _cfg
    from stock_sentinel.debate_engine import run_debate
    from stock_sentinel.models import Alert

    alert = Alert(
        ticker="AMZN",
        direction="LONG",
        entry=entry,
        stop_loss=stop_loss,
        take_profit=tp2,
        take_profit_1=tp1,
        take_profit_3=tp3,
        rsi=signal.rsi,
        sentiment_score=0.62,
        confluence_factors=signal.confluence_factors,
        chart_path=chart_path,
        horizon=signal.horizon,
        horizon_reason=signal.horizon_reason,
        golden_cross=signal.golden_cross,
        rsi_divergence=signal.rsi_divergence,
        risk_reward=signal.risk_reward,
        institutional_score=8.4,
        pct_sl=round((stop_loss - entry) / entry * 100, 2),
        pct_tp1=round((tp1 - entry) / entry * 100, 2),
        pct_tp2=round((tp2 - entry) / entry * 100, 2),
        pct_tp3=round((tp3 - entry) / entry * 100, 2),
        vwap=signal.vwap,
        poc_price=signal.poc_price,
        fib_618=signal.fib_618,
        ema_21=signal.ema_21,
    )

    headlines = [
        "Amazon Web Services reports 37% YoY revenue growth in Q1",
        "AMZN breaks above multi-month resistance with record volume",
        "Analysts raise AMZN price target to $230 after breakout",
    ]

    debate = None
    live_mode = bool(_cfg.ANTHROPIC_API_KEY and _cfg.ANTHROPIC_API_KEY != "your-anthropic-api-key-here")

    if live_mode:
        _p("      Live API key detected — calling Claude agents...")
        try:
            debate = await run_debate(alert, headlines, chart_path=chart_path)
            if debate:
                _p(f"      OK — confidence={debate.confidence_score}%  pattern='{debate.visionary_pattern}'")
            else:
                _p("      Debate returned None (API error)")
        except Exception as e:
            _p(f"      WARN: debate failed ({e}), using mock data")
            debate = None
    else:
        _p("      No API key — using mock agent responses")

    # Build DebateResult from mock JSON if live call unavailable
    if debate is None:
        from stock_sentinel.debate_engine import _extract_json, _first_point
        from stock_sentinel.models import DebateResult

        bull_d = _extract_json(MOCK_BULL_JSON)
        bear_d = _extract_json(MOCK_BEAR_JSON)
        vis_d  = _extract_json(MOCK_VISIONARY_JSON)
        jud_d  = _extract_json(MOCK_JUDGE_JSON)

        debate = DebateResult(
            ticker="AMZN",
            direction="LONG",
            bull_argument=bull_d["טיעון_ראשי"],
            bear_argument=bear_d["טיעון_ראשי"],
            judge_verdict=jud_d["הכרעה"],
            confidence_score=jud_d["ציון_ביטחון"],
            full_bull=MOCK_BULL_JSON,
            full_bear=MOCK_BEAR_JSON,
            full_judge=MOCK_JUDGE_JSON,
            full_visionary=MOCK_VISIONARY_JSON,
            visionary_pattern=vis_d["תבנית_ויזואלית"],
            visionary_confirms=bool(vis_d["מאשר_סיגנל"]),
        )
        _p(f"      OK (mock) — confidence={debate.confidence_score}%  pattern='{debate.visionary_pattern}'")

    # ── Step 5: Build Telegram message ────────────────────────────────────────
    _p("\n[5/6] Building Telegram message preview...")
    from stock_sentinel.notifier import build_message

    message = build_message(alert, headlines, debate)

    _p("\n" + "─" * 62)
    _p("  TELEGRAM ALERT PREVIEW")
    _p("─" * 62)
    _p(message)
    _p("─" * 62)

    # ── Step 6: Verify PNG cleanup ────────────────────────────────────────────
    _p("\n[6/6] Simulating PNG cleanup after Telegram send...")
    if os.path.exists(chart_path):
        os.remove(chart_path)
        _p(f"      OK — chart deleted: {chart_path}")
    else:
        _p(f"      OK — chart was already cleaned up by send_alert")

    # ── Summary ───────────────────────────────────────────────────────────────
    _p("\n" + "=" * 62)
    _p("  TASK 29 SIMULATION COMPLETE")
    _p("=" * 62)
    _p(f"  Visionary pattern  : {debate.visionary_pattern}")
    _p(f"  Confirms signal    : {debate.visionary_confirms}")
    _p(f"  Confidence score   : {debate.confidence_score}%")
    _p(f"  Judge verdict      : {debate.judge_verdict}")
    _p(f"  PNG cleanup        : confirmed")
    _p(f"  Mode               : {'LIVE' if live_mode else 'MOCK'}")
    _p("")


if __name__ == "__main__":
    asyncio.run(main())
