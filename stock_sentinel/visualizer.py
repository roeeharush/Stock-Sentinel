"""
Expert-tier chart generator for Stock Sentinel.

Produces a dark-theme candlestick chart including:
  - SMA 50 (orange) and EMA 200 (red)
  - Rolling VWAP 20-bar (blue dashed)
  - Fibonacci Golden Pocket (61.8%–65.0%) shaded band
  - Volume Profile POC horizontal line
  - Horizontal trade levels: Entry, SL, TP1, TP2, TP3
"""

import os
import tempfile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import mplfinance as mpf
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from stock_sentinel.models import TechnicalSignal

_PLOT_BARS = 50


def generate_chart(ticker: str, df: pd.DataFrame, signal: TechnicalSignal) -> str:
    """Generate an advanced technical chart PNG.  Returns the temp file path."""
    df_full = df.copy()
    n = min(_PLOT_BARS, len(df_full))
    plot_df = df_full.tail(n).copy()

    # ── Pre-compute overlays on the full series, then slice ──────────────────
    ma50_series   = df_full["Close"].rolling(50).mean()
    ema200_series = df_full["Close"].ewm(span=200, adjust=False).mean()
    typical       = (df_full["High"] + df_full["Low"] + df_full["Close"]) / 3.0
    vol_s         = df_full["Volume"].astype(float)
    vwap_series   = (typical * vol_s).rolling(20).sum() / vol_s.rolling(20).sum()

    ma50_plot   = ma50_series.iloc[-n:].reindex(plot_df.index)
    ema200_plot = ema200_series.iloc[-n:].reindex(plot_df.index)
    vwap_plot   = vwap_series.iloc[-n:].reindex(plot_df.index)

    adds = [
        mpf.make_addplot(ma50_plot,   color="#F5A623", width=1.5, label="SMA50"),
        mpf.make_addplot(ema200_plot, color="#D0021B", width=1.5, label="EMA200"),
        mpf.make_addplot(vwap_plot,   color="#4A90E2", width=1.2, linestyle="--", label="VWAP"),
    ]

    path = os.path.join(
        tempfile.gettempdir(),
        f"sentinel_{ticker}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.png",
    )

    fig, axes = mpf.plot(
        plot_df,
        type="candle",
        style="nightclouds",
        addplot=adds,
        title=f"  {ticker}  |  RSI {signal.rsi:.1f}  |  {signal.direction}",
        returnfig=True,
        figsize=(13, 7),
        volume=True,
        panel_ratios=(4, 1),
    )

    ax = axes[0]   # main price panel

    # ── Fibonacci Golden Pocket (61.8%–65.0%) ───────────────────────────────
    if signal.fib_618 and signal.fib_65 and signal.fib_65 != signal.fib_618:
        fib_lo = min(signal.fib_618, signal.fib_65)
        fib_hi = max(signal.fib_618, signal.fib_65)
        ax.axhspan(fib_lo, fib_hi, alpha=0.18, color="#FFD700", zorder=1)
        ax.axhline(fib_lo, color="#FFD700", linewidth=0.7, linestyle=":", alpha=0.75)
        ax.axhline(fib_hi, color="#FFD700", linewidth=0.7, linestyle=":", alpha=0.75)
        ax.text(
            0.01, (fib_lo + fib_hi) / 2,
            "Golden Pocket 0.618–0.65",
            transform=ax.get_yaxis_transform(),
            fontsize=7, color="#FFD700", va="center", alpha=0.9,
        )

    # ── POC line ─────────────────────────────────────────────────────────────
    if signal.poc_price and signal.poc_price > 0:
        ax.axhline(signal.poc_price, color="#FF8C00", linewidth=1.1,
                   linestyle=(0, (3, 2)), alpha=0.8)
        ax.text(
            0.01, signal.poc_price,
            f" POC ${signal.poc_price:.2f}",
            transform=ax.get_yaxis_transform(),
            fontsize=7, color="#FF8C00", va="bottom", alpha=0.9,
        )

    # ── Trade levels ─────────────────────────────────────────────────────────
    levels = [
        (signal.entry,         "#FFFFFF", 1.6, "-",  "Entry"),
        (signal.stop_loss,     "#FF4444", 1.3, "--", "SL"),
        (signal.take_profit_1, "#90EE90", 1.1, "-.", "TP1"),
        (signal.take_profit,   "#00CC44", 1.3, "-.", "TP2"),
        (signal.take_profit_3, "#00FF88", 1.6, "-.", "TP3"),
    ]
    for price, color, lw, ls, label in levels:
        if price and price > 0:
            ax.axhline(price, color=color, linewidth=lw, linestyle=ls, alpha=0.88)
            ax.text(
                0.99, price,
                f"{label} ${price:.2f} ",
                transform=ax.get_yaxis_transform(),
                fontsize=7, color=color, va="bottom", ha="right", alpha=0.95,
            )

    fig.patch.set_facecolor("#131722")
    for axis in axes:
        axis.set_facecolor("#131722")

    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)
    return path
