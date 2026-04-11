import asyncio
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from stock_sentinel import config
from stock_sentinel.config import validate_secrets
from stock_sentinel.models import TickerSnapshot, Alert
from stock_sentinel.analyzer import fetch_ohlcv, compute_signals
from stock_sentinel.scraper import init_browser, scrape_sentiment, close_browser, save_cookies
from stock_sentinel.news_scraper import fetch_news_sentiment
from stock_sentinel.rss_provider import fetch_rss_sentiment
from stock_sentinel.signal_filter import combined_sentiment_score, should_alert, update_cooldown
from stock_sentinel.notifier import generate_chart, send_alert, send_daily_report
from stock_sentinel.db import init_db, log_alert, get_daily_stats
from stock_sentinel.monitor import check_active_trades
from stock_sentinel.validator import validate_daily

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


async def _async_cycle(
    tickers: list[str],
    state: dict[str, TickerSnapshot],
    page,
) -> None:
    """Run one monitoring cycle for all tickers. Page is injected for testability."""
    consecutive_failures = 0
    circuit_open = False

    for ticker in tickers:
        if circuit_open:
            break

        snap = state.setdefault(ticker, TickerSnapshot(ticker=ticker))
        try:
            # --- Data Acquisition ---
            sentiment = await scrape_sentiment(ticker, page)
            snap.sentiment = sentiment

            if sentiment.failed:
                consecutive_failures += 1
                log.warning("%s: scrape failed (%d consecutive)", ticker, consecutive_failures)
                if consecutive_failures >= config.SCRAPER_CIRCUIT_BREAKER_N:
                    circuit_open = True
            else:
                consecutive_failures = 0

            if circuit_open:
                continue  # skip to next iteration, break happens at loop top

            snap.news_sentiment = fetch_news_sentiment(ticker)
            snap.rss_sentiment = fetch_rss_sentiment(ticker)

            try:
                df = fetch_ohlcv(ticker)
                snap.technical = compute_signals(ticker, df)
            except ValueError as exc:
                log.warning("%s: technical analysis skipped — %s", ticker, exc)
                continue

            # --- Filtering & Action ---
            if not should_alert(snap):
                continue

            score = combined_sentiment_score(snap)
            headlines = snap.news_sentiment.headlines if snap.news_sentiment else []
            chart_path = generate_chart(ticker, df, snap.technical)

            alert = Alert(
                ticker=ticker,
                direction=snap.technical.direction,
                entry=snap.technical.entry,
                stop_loss=snap.technical.stop_loss,
                take_profit=snap.technical.take_profit,
                take_profit_1=snap.technical.take_profit_1,
                take_profit_3=snap.technical.take_profit_3,
                rsi=snap.technical.rsi,
                sentiment_score=score,
                twitter_score=snap.sentiment.score if snap.sentiment else 0.0,
                news_score=snap.news_sentiment.score if snap.news_sentiment else 0.0,
                rss_score=snap.rss_sentiment.score if snap.rss_sentiment else 0.0,
                confluence_factors=snap.technical.confluence_factors,
                horizon=snap.technical.horizon,
                horizon_reason=snap.technical.horizon_reason,
                chart_path=chart_path,
            )

            message_id = await send_alert(
                alert, headlines, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
            )
            if message_id is not None:
                log_alert(
                    alert,
                    technical_score=snap.technical.technical_score,
                    telegram_message_id=message_id,
                )
                state[ticker] = update_cooldown(snap)
                log.info("Alert sent: %s %s", ticker, snap.technical.direction)

        except Exception as exc:  # noqa: BLE001 — ticker-level isolation
            log.error("%s: unexpected error in cycle — %s: %s", ticker, type(exc).__name__, exc)

    # Fire circuit breaker admin alert outside the per-ticker loop
    if circuit_open:
        log.error("Circuit breaker triggered — pausing scraper for this cycle")
        cb_alert = Alert(
            ticker="SYSTEM",
            direction="LONG",
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            rsi=0.0,
            sentiment_score=0.0,
        )
        try:
            await send_alert(
                cb_alert,
                [],
                config.TELEGRAM_BOT_TOKEN,
                config.TELEGRAM_CHAT_ID,
            )
        except Exception as exc:
            log.error("Failed to send circuit breaker alert: %s", exc)


def run_cycle(state: dict[str, TickerSnapshot]) -> None:
    """Synchronous entry point called by APScheduler."""
    asyncio.run(_run_with_browser(state))


async def _run_with_browser(state: dict[str, TickerSnapshot]) -> None:
    """Manages browser lifecycle for a full cycle."""
    pw = browser = page = None
    try:
        pw, browser, page = await init_browser(config.X_COOKIES_PATH)
        await _async_cycle(config.WATCHLIST, state, page)
    finally:
        if page is not None:
            await save_cookies(page, config.X_COOKIES_PATH)
        if pw is not None and browser is not None:
            await close_browser(pw, browser)


def run_validation() -> None:
    """Synchronous APScheduler entry point for the daily validator."""
    try:
        result = validate_daily()
        log.info("Validation complete: %s", result)
    except Exception as exc:
        log.error("Validation failed: %s", exc)


def run_daily_report() -> None:
    """Synchronous APScheduler entry point for the daily performance report."""
    try:
        stats = get_daily_stats()
        asyncio.run(
            send_daily_report(stats, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
        )
        log.info("Daily report sent. Win rate: %.0f%%", stats.get("win_rate", 0) * 100)
    except Exception as exc:
        log.error("Daily report failed: %s", exc)


def run_monitor() -> None:
    """Synchronous APScheduler entry point for the live trade monitor."""
    try:
        result = asyncio.run(
            check_active_trades(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
        )
        if result["updates_sent"]:
            log.info("Monitor: sent %d trade update(s)", result["updates_sent"])
    except Exception as exc:
        log.error("Monitor run failed: %s", exc)


def main() -> None:
    validate_secrets()
    init_db()
    state: dict[str, TickerSnapshot] = {}
    scheduler = BlockingScheduler(timezone="America/New_York")

    # Intraday monitoring: every 15 min, 9:00–15:45 ET, Mon–Fri
    scheduler.add_job(
        run_cycle,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="0,15,30,45",
            timezone="America/New_York",
        ),
        args=[state],
    )

    # Post-market validator: 16:30 ET, Mon–Fri
    scheduler.add_job(
        run_validation,
        CronTrigger(
            day_of_week="mon-fri",
            hour="16",
            minute="30",
            timezone="America/New_York",
        ),
    )

    # Daily performance report: 17:00 ET, Mon–Fri
    scheduler.add_job(
        run_daily_report,
        CronTrigger(
            day_of_week="mon-fri",
            hour="17",
            minute="0",
            timezone="America/New_York",
        ),
    )

    # Live trade monitor: every 2 minutes, 9:30–16:00 ET, Mon–Fri
    scheduler.add_job(
        run_monitor,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/2",
            timezone="America/New_York",
        ),
    )

    log.info("Stock Sentinel started. Watching: %s", ", ".join(config.WATCHLIST))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
