import asyncio
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from stock_sentinel import config
from stock_sentinel.config import validate_secrets
from stock_sentinel.models import TickerSnapshot, Alert
from stock_sentinel.analyzer import fetch_ohlcv, compute_signals
from stock_sentinel.scraper import init_browser, scrape_sentiment, close_browser, save_cookies
from stock_sentinel.news_scraper import fetch_news_sentiment
from stock_sentinel.rss_provider import fetch_rss_sentiment
from stock_sentinel.signal_filter import combined_sentiment_score, should_alert, update_cooldown, DynamicBlacklist
from stock_sentinel.notifier import (
    generate_chart, send_alert, send_daily_report,
    send_news_flash, send_macro_flash, send_smart_money_alert,
    send_learning_report,
)
from stock_sentinel.db import init_db, log_alert, get_daily_stats
from stock_sentinel.monitor import check_active_trades
from stock_sentinel.validator import validate_daily
from stock_sentinel.scanner import (
    ScannerCooldownTracker,
    fetch_market_movers,
    filter_candidates,
)
from stock_sentinel.signal_filter import combined_sentiment_score as _css
from stock_sentinel.news_engine import NewsEngineState, run_news_engine_cycle
from stock_sentinel.deep_data_engine import DeepDataState, run_deep_data_cycle
from stock_sentinel.debate_engine import run_debate
from stock_sentinel.learning_engine import run_weekly_learning
from stock_sentinel import config as _cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


async def _async_cycle(
    tickers: list[str],
    state: dict[str, TickerSnapshot],
    page,
    blacklist: DynamicBlacklist | None = None,
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
            except ValueError as exc:
                log.warning("%s: skipped — OHLCV fetch failed: %s", ticker, exc)
                continue
            if df is None or df.empty or len(df) < 50:
                log.warning(
                    "%s: skipped — insufficient OHLCV data (%d bars, need 50)",
                    ticker, len(df) if df is not None else 0,
                )
                continue
            try:
                snap.technical = compute_signals(ticker, df)
            except ValueError as exc:
                log.warning("%s: skipped — signal computation failed: %s", ticker, exc)
                continue

            # --- Filtering & Action ---
            if not should_alert(snap, blacklist=blacklist):
                continue

            score = combined_sentiment_score(snap)
            headlines = snap.news_sentiment.headlines if snap.news_sentiment else []
            chart_path = generate_chart(ticker, df, snap.technical)

            # ── Compute Expert Tier fields ─────────────────────────────────
            t = snap.technical
            entry = t.entry

            def _pct(price: float) -> float:
                return round((price - entry) / entry * 100.0, 1) if entry else 0.0

            # Institutional score: blend of technical (0-7) + sentiment (0-3)
            ts_component = t.technical_score * 7.0 / 100.0
            ss_component = (score + 1.0) * 1.5
            institutional_score = round(
                min(max(ts_component + ss_component, 1.0), 10.0), 1
            )

            # ── High-probability gate: scan continues, alert is silent ─────
            if institutional_score < config.INSTITUTIONAL_SCORE_MIN:
                log.debug(
                    "%s: institutional_score %.1f < %.1f — scan complete, no alert fired",
                    ticker, institutional_score, config.INSTITUTIONAL_SCORE_MIN,
                )
                continue

            alert = Alert(
                ticker=ticker,
                direction=t.direction,
                entry=entry,
                stop_loss=t.stop_loss,
                take_profit=t.take_profit,
                take_profit_1=t.take_profit_1,
                take_profit_3=t.take_profit_3,
                rsi=t.rsi,
                sentiment_score=score,
                twitter_score=snap.sentiment.score if snap.sentiment else 0.0,
                news_score=snap.news_sentiment.score if snap.news_sentiment else 0.0,
                rss_score=snap.rss_sentiment.score if snap.rss_sentiment else 0.0,
                confluence_factors=t.confluence_factors,
                horizon=t.horizon,
                horizon_reason=t.horizon_reason,
                chart_path=chart_path,
                # Expert Tier
                institutional_score=institutional_score,
                pct_sl=_pct(t.stop_loss),
                pct_tp1=_pct(t.take_profit_1),
                pct_tp2=_pct(t.take_profit),
                pct_tp3=_pct(t.take_profit_3),
                vwap=t.vwap,
                poc_price=t.poc_price,
                fib_618=t.fib_618,
                golden_cross=t.golden_cross,
                rsi_divergence=t.rsi_divergence,
                pivot_r1=t.pivot_r1,
                pivot_r2=t.pivot_r2,
                pivot_s1=t.pivot_s1,
                pivot_s2=t.pivot_s2,
            )

            # Optional: run Multi-Agent Debate + Vision before sending
            debate = None
            if _cfg.debate_enabled():
                try:
                    debate = await run_debate(alert, headlines, chart_path=chart_path)
                except Exception as exc:
                    log.warning("Debate engine skipped for %s: %s", ticker, exc)

            message_id = await send_alert(
                alert, headlines, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID,
                debate=debate,
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

    # Circuit breaker: log only — do NOT create an Alert object or call send_alert.
    # Sending a fake SYSTEM ticker through the trade-alert path produces phantom
    # alerts with 0.0 financial values.  PM2 log captures this error line instead.
    if circuit_open:
        log.error(
            "Circuit breaker triggered — scraper paused for this cycle after %d consecutive failures",
            config.SCRAPER_CIRCUIT_BREAKER_N,
        )


def run_cycle(state: dict[str, TickerSnapshot], blacklist: DynamicBlacklist | None = None) -> None:
    """Synchronous entry point called by APScheduler."""
    asyncio.run(_run_with_browser(state, blacklist))


async def _run_with_browser(
    state: dict[str, TickerSnapshot],
    blacklist: DynamicBlacklist | None = None,
) -> None:
    """Manages browser lifecycle for a full cycle."""
    pw = browser = page = None
    try:
        pw, browser, page = await init_browser(config.X_COOKIES_PATH)
        await _async_cycle(config.WATCHLIST, state, page, blacklist=blacklist)
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


async def _async_scanner_cycle(scanner_state: ScannerCooldownTracker) -> None:
    """Fetch market movers, filter them, run full analysis, send alerts for qualified hits."""
    candidates = await fetch_market_movers()
    qualified  = filter_candidates(candidates, scanner_state)

    # ── Smoke-test rate limiter ───────────────────────────────────────────────
    # Set config.SMOKE_TEST_LIMIT = 0 (or remove) to disable.
    # While INSTITUTIONAL_SCORE_MIN is lowered for testing, this cap prevents
    # flooding the Telegram channel.
    _smoke_limit = getattr(config, "SMOKE_TEST_LIMIT", 0)
    alerts_sent  = 0

    for cand in qualified:
        if _smoke_limit > 0 and alerts_sent >= _smoke_limit:
            log.info("Smoke test limit reached (%d/%d alerts sent) — stopping cycle early", alerts_sent, _smoke_limit)
            break
        ticker = cand.ticker
        try:
            try:
                df = fetch_ohlcv(ticker)
            except ValueError as exc:
                log.warning("Scanner skip %s: OHLCV fetch failed — %s", ticker, exc)
                continue
            if df is None or df.empty or len(df) < 50:
                log.warning(
                    "Scanner skip %s: insufficient OHLCV data (%d bars, need 50)",
                    ticker, len(df) if df is not None else 0,
                )
                continue
            try:
                signal = compute_signals(ticker, df)
            except ValueError as exc:
                log.warning("Scanner skip %s: signal computation failed — %s", ticker, exc)
                continue

            if signal.direction == "NEUTRAL":
                continue

            # R/R gate: skip if below minimum risk/reward
            if signal.risk_reward > 0 and signal.risk_reward < config.RR_MIN:
                log.debug("Scanner skip %s: RR %.2f < %.2f", ticker, signal.risk_reward, config.RR_MIN)
                continue

            # Sentiment: use news + RSS only (no browser required for scanner)
            snap = TickerSnapshot(ticker=ticker)
            snap.technical      = signal
            snap.news_sentiment = fetch_news_sentiment(ticker)
            snap.rss_sentiment  = fetch_rss_sentiment(ticker)

            score    = _css(snap)
            headlines = snap.news_sentiment.headlines if snap.news_sentiment else []

            # Direction + sentiment agreement
            if signal.direction == "LONG" and score <= 0:
                continue
            if signal.direction == "SHORT" and score >= 0:
                continue

            chart_path = generate_chart(ticker, df, signal)

            t     = signal
            entry = t.entry

            def _pct(price: float) -> float:
                return round((price - entry) / entry * 100.0, 1) if entry else 0.0

            ts_component   = t.technical_score * 7.0 / 100.0
            ss_component   = (score + 1.0) * 1.5
            inst_score     = round(min(max(ts_component + ss_component, 1.0), 10.0), 1)

            # ── High-probability gate: scan continues, alert is silent ─────
            if inst_score < config.INSTITUTIONAL_SCORE_MIN:
                log.debug(
                    "Scanner skip %s: institutional_score %.1f < %.1f — no alert fired",
                    ticker, inst_score, config.INSTITUTIONAL_SCORE_MIN,
                )
                continue

            alert = Alert(
                ticker=ticker,
                direction=t.direction,
                entry=entry,
                stop_loss=t.stop_loss,
                take_profit=t.take_profit,
                take_profit_1=t.take_profit_1,
                take_profit_3=t.take_profit_3,
                rsi=t.rsi,
                sentiment_score=score,
                news_score=snap.news_sentiment.score if snap.news_sentiment else 0.0,
                rss_score=snap.rss_sentiment.score if snap.rss_sentiment else 0.0,
                confluence_factors=t.confluence_factors,
                horizon=t.horizon,
                horizon_reason=t.horizon_reason,
                chart_path=chart_path,
                institutional_score=inst_score,
                pct_sl=_pct(t.stop_loss),
                pct_tp1=_pct(t.take_profit_1),
                pct_tp2=_pct(t.take_profit),
                pct_tp3=_pct(t.take_profit_3),
                vwap=t.vwap,
                poc_price=t.poc_price,
                fib_618=t.fib_618,
                golden_cross=t.golden_cross,
                rsi_divergence=t.rsi_divergence,
                pivot_r1=t.pivot_r1,
                pivot_r2=t.pivot_r2,
                pivot_s1=t.pivot_s1,
                pivot_s2=t.pivot_s2,
                scanner_hit=True,
                risk_reward=t.risk_reward,
                ema_21=t.ema_21,
            )

            # Optional: run Multi-Agent Debate + Vision for scanner hits too
            debate = None
            if _cfg.debate_enabled():
                try:
                    debate = await run_debate(alert, headlines, chart_path=chart_path)
                except Exception as exc:
                    log.warning("Scanner debate skipped for %s: %s", ticker, exc)

            message_id = await send_alert(
                alert, headlines, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID,
                debate=debate,
            )
            if message_id is not None:
                log_alert(alert, technical_score=t.technical_score, telegram_message_id=message_id)
                scanner_state.mark_alerted(ticker, entry)
                log.info("Scanner alert sent: %s %s (RR=%.2f)", ticker, t.direction, t.risk_reward)
                alerts_sent += 1

        except Exception as exc:
            log.error("Scanner: unexpected error for %s — %s: %s", ticker, type(exc).__name__, exc)


def run_scanner(scanner_state: ScannerCooldownTracker) -> None:
    """Synchronous APScheduler entry point for the autonomous market scanner."""
    try:
        asyncio.run(_async_scanner_cycle(scanner_state))
    except Exception as exc:
        log.error("Scanner cycle failed: %s", exc)


async def _async_news_engine_cycle(news_state: NewsEngineState) -> None:
    """Fetch breaking news + macro alerts, filter, and send Telegram messages."""
    flashes, macro_flashes = await run_news_engine_cycle(config.WATCHLIST, news_state)

    for flash in flashes:
        try:
            sent = await send_news_flash(flash, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
            if sent:
                log.info(
                    "News flash sent: %s — %s [%s]",
                    flash.ticker, flash.reaction, ", ".join(flash.catalyst_keywords[:3]),
                )
        except Exception as exc:
            log.error("News flash dispatch failed for %s: %s", flash.ticker, exc)

    for mflash in macro_flashes:
        try:
            sent = await send_macro_flash(mflash, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
            if sent:
                log.info(
                    "Macro flash sent: %s — %s [%s]",
                    mflash.reaction, mflash.source, ", ".join(mflash.influencers[:3]),
                )
        except Exception as exc:
            log.error("Macro flash dispatch failed: %s", exc)


def run_news_engine(news_state: NewsEngineState) -> None:
    """Synchronous APScheduler entry point for the real-time news catalyst engine."""
    try:
        asyncio.run(_async_news_engine_cycle(news_state))
    except Exception as exc:
        log.error("News engine cycle failed: %s", exc)


async def _async_deep_data_cycle(deep_state: DeepDataState) -> None:
    """Fetch insider purchases + unusual options flow, send alerts for new hits."""
    insider_alerts, options_alerts = await run_deep_data_cycle(config.WATCHLIST, deep_state)

    for alert in insider_alerts:
        try:
            sent = await send_smart_money_alert(
                alert, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
            )
            if sent:
                log.info(
                    "Insider alert sent: %s — %s purchased $%.0f",
                    alert.ticker, alert.insider_name, alert.value,
                )
        except Exception as exc:
            log.error("Insider alert dispatch failed for %s: %s", alert.ticker, exc)

    for alert in options_alerts:
        try:
            sent = await send_smart_money_alert(
                alert, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
            )
            if sent:
                log.info(
                    "Options flow alert sent: %s %s $%.1f exp=%s vol=%d (%.1fx OI)",
                    alert.ticker, alert.option_type, alert.strike,
                    alert.expiry, alert.volume, alert.volume_oi_ratio,
                )
        except Exception as exc:
            log.error("Options flow alert dispatch failed for %s: %s", alert.ticker, exc)


def run_deep_data(deep_state: DeepDataState) -> None:
    """Synchronous APScheduler entry point for the Deep Data Engine."""
    try:
        asyncio.run(_async_deep_data_cycle(deep_state))
    except Exception as exc:
        log.error("Deep data cycle failed: %s", exc)


def run_learning_engine(blacklist: DynamicBlacklist) -> None:
    """Synchronous APScheduler entry point: analyse last week, update blacklist, send report."""
    try:
        report = run_weekly_learning(days=7)
        log.info(
            "Learning engine: %d resolved trades, %.0f%% win rate before → %.0f%% after, "
            "%d patterns, %d trades filtered",
            report.total_trades,
            report.win_rate_before * 100,
            report.win_rate_after * 100,
            len(report.patterns),
            report.trades_filtered,
        )
        # Update the live blacklist used by all next-week cycles
        if report.patterns:
            blacklist.apply_report(report)
        else:
            blacklist.clear()

        asyncio.run(
            send_learning_report(report, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
        )
    except Exception as exc:
        log.error("Learning engine failed: %s", exc)


def main() -> None:
    validate_secrets()
    init_db()
    state: dict[str, TickerSnapshot] = {}
    scanner_state = ScannerCooldownTracker()
    news_state    = NewsEngineState()
    deep_state    = DeepDataState()
    blacklist     = DynamicBlacklist()
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
        args=[state, blacklist],
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

    # Autonomous Market Hunter: every 15 min, 9:30–15:45 ET, Mon–Fri
    scheduler.add_job(
        run_scanner,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="0,15,30,45",
            timezone="America/New_York",
        ),
        args=[scanner_state],
    )

    # Real-time News Catalyst Engine: every 5 minutes, 24/7 — no market-hour
    # restriction.  next_run_time=now() fires the first cycle immediately on
    # startup instead of waiting a full interval.
    scheduler.add_job(
        run_news_engine,
        IntervalTrigger(
            minutes=config.NEWS_ENGINE_POLL_MINUTES,
        ),
        args=[news_state],
        next_run_time=datetime.now(timezone.utc),
    )

    # Deep Data Engine: every hour 10:00–15:00 ET (market hours), Mon–Fri
    scheduler.add_job(
        run_deep_data,
        CronTrigger(
            day_of_week="mon-fri",
            hour="10-15",
            minute="0",
            timezone="America/New_York",
        ),
        args=[deep_state],
    )

    # Deep Data Engine: post-market scan at 16:05 ET, Mon–Fri
    scheduler.add_job(
        run_deep_data,
        CronTrigger(
            day_of_week="mon-fri",
            hour="16",
            minute="5",
            timezone="America/New_York",
        ),
        args=[deep_state],
    )

    # Self-Learning Engine: every Saturday at 18:00 ET
    scheduler.add_job(
        run_learning_engine,
        CronTrigger(
            day_of_week="sat",
            hour="18",
            minute="0",
            timezone="America/New_York",
        ),
        args=[blacklist],
    )

    log.info("Stock Sentinel started. Watching: %s", ", ".join(config.WATCHLIST))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
