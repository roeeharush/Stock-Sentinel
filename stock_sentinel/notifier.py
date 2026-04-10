import os
import tempfile
import asyncio
import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf
import pandas as pd
from datetime import datetime, timezone
from telegram import Bot
from telegram.error import TelegramError
from stock_sentinel.models import Alert, TechnicalSignal


def build_message(alert: Alert, headlines: list[str]) -> str:
    """Build Telegram message with technical data, sentiment breakdown, and headlines."""
    lines = [
        f"📊 *Stock Sentinel — {alert.ticker}* | {alert.direction}",
        "",
        "*Technical*",
        f"  Entry:       ${alert.entry:.2f}",
        f"  Stop Loss:   ${alert.stop_loss:.2f}",
        f"  Take Profit: ${alert.take_profit:.2f}",
        f"  RSI:         {alert.rsi:.1f}",
        "",
        "*Sentiment* (60% news / 40% twitter)",
        f"  Combined:  {alert.sentiment_score:+.2f}",
        f"  Twitter:   {alert.twitter_score:+.2f}",
        f"  News:      {alert.news_score:+.2f}",
    ]
    if headlines:
        lines += ["", "*Top Headlines*"]
        for h in headlines[:5]:
            lines.append(f"  • {h}")
    lines += ["", f"_{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC_"]
    return "\n".join(lines)


def generate_chart(ticker: str, df: pd.DataFrame, signal: TechnicalSignal) -> str:
    """Generate candlestick chart with SMA20/SMA50 overlays. Returns temp file path."""
    df_full = df.copy()
    ma20_full = df_full["Close"].rolling(20).mean()
    ma50_full = df_full["Close"].rolling(50).mean()
    plot_df = df_full.tail(30)
    ma20 = ma20_full.iloc[-30:]
    ma50 = ma50_full.iloc[-30:]
    adds = [
        mpf.make_addplot(ma20, color="blue", width=1.2, label="SMA20"),
        mpf.make_addplot(ma50, color="orange", width=1.2, label="SMA50"),
    ]
    path = os.path.join(
        tempfile.gettempdir(),
        f"stock_sentinel_{ticker}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.png",
    )
    mpf.plot(
        plot_df,
        type="candle",
        style="charles",
        addplot=adds,
        title=f"{ticker} | RSI: {signal.rsi:.1f} | {signal.direction}",
        savefig=dict(fname=path, dpi=150, bbox_inches="tight"),
        figsize=(10, 6),
    )
    return path


async def send_alert(
    alert: Alert, headlines: list[str], bot_token: str, chat_id: str
) -> bool:
    """Send alert via Telegram with 3 retries. Returns True on success."""
    bot = Bot(token=bot_token)
    text = build_message(alert, headlines)
    for attempt in range(3):
        try:
            if alert.chart_path and os.path.exists(alert.chart_path):
                with open(alert.chart_path, "rb") as photo:
                    await bot.send_photo(
                        chat_id=chat_id, photo=photo, caption=text, parse_mode="Markdown"
                    )
            else:
                await bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="Markdown"
                )
            return True
        except TelegramError:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt * 2)
    return False
