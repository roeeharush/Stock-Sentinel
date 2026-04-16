"""Deep Data Engine — Insider Tracker + Unusual Options Flow Detector.

Runs on an hourly schedule during market hours (10:00–15:00 ET) and once
post-market (16:05 ET).  First cycle primes the dedup sets silently so
existing data never floods on startup.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf

from stock_sentinel import config
from stock_sentinel.models import InsiderAlert, OptionsFlowAlert

log = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
_INSIDER_MIN_VALUE      = 100_000   # USD — ignore small/symbolic purchases
_OPTIONS_MIN_VOLUME     = 1_000     # absolute floor
# Volume/OI ratio is now driven by config.OPTIONS_VOLUME_OI_MIN_RATIO (default 5.0).
# Edit that constant in config.py to adjust strictness without touching this file.
_OPTIONS_TOP_N          = 5         # return at most N options hits per ticker
_OPTIONS_DEDUP_HOURS    = 1         # same contract is silent for this many hours


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

class DeepDataState:
    """Warm-up + dedup tracking for the Deep Data Engine.

    Mirrors the NewsEngineState design:
      - First cycle: primes the seen-sets without emitting alerts.
      - Subsequent cycles: only new items emit alerts.
    """

    def __init__(self) -> None:
        self._seen_insider: set[str] = set()
        # Maps dedup-key → first-seen UTC datetime.
        # Key is ticker|expiry|strike|option_type (volume intentionally excluded
        # so the same contract cannot re-fire every hour with a slightly different count).
        self._seen_options: dict[str, datetime] = {}
        self._warmed_up: bool = False

    @property
    def warmed_up(self) -> bool:
        return self._warmed_up

    def mark_warmed_up(self) -> None:
        self._warmed_up = True

    def is_options_seen(self, key: str) -> bool:
        """Return True if this options contract key was seen within the dedup window."""
        seen_at = self._seen_options.get(key)
        if seen_at is None:
            return False
        return datetime.now(timezone.utc) - seen_at < timedelta(hours=_OPTIONS_DEDUP_HOURS)

    def mark_options_seen(self, key: str) -> None:
        self._seen_options[key] = datetime.now(timezone.utc)

    def clear(self) -> None:
        self._seen_insider.clear()
        self._seen_options.clear()
        self._warmed_up = False


# ─────────────────────────────────────────────────────────────────────────────
# Fetch helpers  (blocking — called via asyncio.to_thread)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_insider_purchases(ticker: str) -> list[InsiderAlert]:
    """Return significant insider purchase transactions for *ticker*.

    Filters:
      - Transaction column contains "Purchase"
      - Value >= _INSIDER_MIN_VALUE USD
    """
    try:
        tk     = yf.Ticker(ticker)
        df     = tk.insider_transactions
        if df is None or df.empty:
            return []

        # Normalise column access — yfinance column names can vary between versions
        required = {"Transaction", "Value", "Insider", "Position", "Shares", "Start Date"}
        if not required.issubset(set(df.columns)):
            log.debug("insider_transactions: unexpected columns for %s: %s", ticker, list(df.columns))
            return []

        purchases = df[df["Transaction"].str.contains("Purchase", case=False, na=False)]
        purchases = purchases[purchases["Value"] >= _INSIDER_MIN_VALUE]

        alerts: list[InsiderAlert] = []
        for _, row in purchases.iterrows():
            raw_date = row["Start Date"]
            if isinstance(raw_date, str):
                try:
                    tx_date = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    tx_date = datetime.now(timezone.utc)
            elif isinstance(raw_date, datetime):
                tx_date = raw_date if raw_date.tzinfo else raw_date.replace(tzinfo=timezone.utc)
            else:
                tx_date = datetime.now(timezone.utc)

            alerts.append(InsiderAlert(
                ticker=ticker,
                insider_name=str(row["Insider"]),
                position=str(row["Position"]),
                shares=int(row["Shares"]),
                value=float(row["Value"]),
                transaction_date=tx_date,
            ))
        return alerts

    except Exception as exc:
        log.warning("_fetch_insider_purchases(%s) failed: %s", ticker, exc)
        return []


def _fetch_unusual_options_flow(ticker: str) -> list[OptionsFlowAlert]:
    """Return unusual-volume options contracts for *ticker*.

    Checks the nearest 4 expiry dates.  An option qualifies when:
      volume >= _OPTIONS_MIN_VOLUME  AND  volume >= _OPTIONS_VOLUME_OI_MULT × open_interest

    Returns at most _OPTIONS_TOP_N contracts ranked by volume/OI ratio (descending).
    """
    try:
        tk      = yf.Ticker(ticker)
        expiries = tk.options           # tuple of expiry date strings
        if not expiries:
            return []

        hits: list[OptionsFlowAlert] = []

        for expiry in expiries[:4]:
            try:
                chain = tk.option_chain(expiry)
            except Exception as exc:
                log.debug("option_chain(%s, %s) failed: %s", ticker, expiry, exc)
                continue

            for opt_type, frame in (("CALL", chain.calls), ("PUT", chain.puts)):
                if frame is None or frame.empty:
                    continue
                needed = {"strike", "volume", "openInterest"}
                if not needed.issubset(set(frame.columns)):
                    continue
                for _, row in frame.iterrows():
                    vol = int(row["volume"]) if not _is_nan(row["volume"]) else 0
                    oi  = int(row["openInterest"]) if not _is_nan(row["openInterest"]) else 0
                    if vol < _OPTIONS_MIN_VOLUME:
                        continue
                    if oi == 0:
                        continue
                    ratio = vol / oi
                    if ratio < config.OPTIONS_VOLUME_OI_MIN_RATIO:
                        continue
                    hits.append(OptionsFlowAlert(
                        ticker=ticker,
                        expiry=expiry,
                        strike=float(row["strike"]),
                        option_type=opt_type,
                        volume=vol,
                        open_interest=oi,
                        volume_oi_ratio=round(ratio, 1),
                    ))

        # Sort by ratio descending, keep top N
        hits.sort(key=lambda h: h.volume_oi_ratio, reverse=True)
        return hits[:_OPTIONS_TOP_N]

    except Exception as exc:
        log.warning("_fetch_unusual_options_flow(%s) failed: %s", ticker, exc)
        return []


def _is_nan(val) -> bool:
    """Safe NaN check that works for int, float, and pandas NA."""
    try:
        import math
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Public async entry point
# ─────────────────────────────────────────────────────────────────────────────

async def run_deep_data_cycle(
    watchlist: list[str],
    state: DeepDataState,
) -> tuple[list[InsiderAlert], list[OptionsFlowAlert]]:
    """Run one deep-data cycle across *watchlist*.

    Returns (insider_alerts, options_alerts) to emit.
    First cycle is silent (warm-up): populates dedup sets without returning alerts.
    """
    warming_up = not state.warmed_up

    new_insiders: list[InsiderAlert] = []
    new_options:  list[OptionsFlowAlert] = []

    for ticker in watchlist:
        # ── Insider purchases ─────────────────────────────────────────────────
        try:
            insider_hits = await asyncio.to_thread(_fetch_insider_purchases, ticker)
        except Exception as exc:
            log.error("Deep data insider fetch error for %s: %s", ticker, exc)
            insider_hits = []

        for hit in insider_hits:
            key = (
                f"{hit.ticker}|{hit.insider_name}|"
                f"{hit.transaction_date.date()}|{hit.shares}"
            )
            if key not in state._seen_insider:
                state._seen_insider.add(key)
                if not warming_up:
                    new_insiders.append(hit)

        # ── Unusual options flow ──────────────────────────────────────────────
        try:
            options_hits = await asyncio.to_thread(_fetch_unusual_options_flow, ticker)
        except Exception as exc:
            log.error("Deep data options fetch error for %s: %s", ticker, exc)
            options_hits = []

        for hit in options_hits:
            # Key excludes volume so the same contract doesn't re-alert each hour
            # simply because its volume ticked up.  The 1-hour dedup window in
            # DeepDataState.is_options_seen() handles the cooldown.
            key = f"{hit.ticker}|{hit.expiry}|{hit.strike}|{hit.option_type}"
            if not state.is_options_seen(key):
                state.mark_options_seen(key)
                if not warming_up:
                    new_options.append(hit)

    if warming_up:
        state.mark_warmed_up()
        log.info(
            "DeepData warm-up complete: %d insider keys, %d options keys",
            len(state._seen_insider), len(state._seen_options),
        )

    return new_insiders, new_options
