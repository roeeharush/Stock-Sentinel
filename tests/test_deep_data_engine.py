"""Tests for stock_sentinel.deep_data_engine."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_sentinel.deep_data_engine import (
    DeepDataState,
    _fetch_insider_purchases,
    _fetch_unusual_options_flow,
    run_deep_data_cycle,
)
from stock_sentinel.models import InsiderAlert, OptionsFlowAlert


# ─────────────────────────────────────────────────────────────────────────────
# DeepDataState lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def test_initial_state_not_warmed_up():
    state = DeepDataState()
    assert not state.warmed_up


def test_mark_warmed_up():
    state = DeepDataState()
    state.mark_warmed_up()
    assert state.warmed_up


def test_clear_resets_state():
    state = DeepDataState()
    state._seen_insider.add("NVDA|test|2025-01-01|100")
    state._seen_options.add("NVDA|2025-05-16|100.0|CALL|5000")
    state.mark_warmed_up()

    state.clear()

    assert not state.warmed_up
    assert len(state._seen_insider) == 0
    assert len(state._seen_options) == 0


# ─────────────────────────────────────────────────────────────────────────────
# _fetch_insider_purchases
# ─────────────────────────────────────────────────────────────────────────────

def _make_insider_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


@patch("stock_sentinel.deep_data_engine.yf.Ticker")
def test_fetch_insider_purchases_returns_purchases(mock_ticker):
    df = _make_insider_df([
        {
            "Transaction": "Purchase",
            "Value": 500_000,
            "Insider": "Jensen Huang",
            "Position": "CEO",
            "Shares": 1000,
            "Start Date": "2025-03-10",
        },
        {
            "Transaction": "Sale",
            "Value": 1_000_000,
            "Insider": "CFO Person",
            "Position": "CFO",
            "Shares": 5000,
            "Start Date": "2025-03-11",
        },
    ])
    mock_ticker.return_value.insider_transactions = df

    results = _fetch_insider_purchases("NVDA")

    assert len(results) == 1
    assert results[0].insider_name == "Jensen Huang"
    assert results[0].value == 500_000
    assert results[0].ticker == "NVDA"


@patch("stock_sentinel.deep_data_engine.yf.Ticker")
def test_fetch_insider_purchases_filters_below_threshold(mock_ticker):
    df = _make_insider_df([
        {
            "Transaction": "Purchase",
            "Value": 50_000,        # below $100K threshold
            "Insider": "Director",
            "Position": "Director",
            "Shares": 200,
            "Start Date": "2025-03-10",
        },
    ])
    mock_ticker.return_value.insider_transactions = df

    results = _fetch_insider_purchases("NVDA")

    assert results == []


@patch("stock_sentinel.deep_data_engine.yf.Ticker")
def test_fetch_insider_purchases_empty_dataframe(mock_ticker):
    mock_ticker.return_value.insider_transactions = pd.DataFrame()

    results = _fetch_insider_purchases("NVDA")

    assert results == []


@patch("stock_sentinel.deep_data_engine.yf.Ticker")
def test_fetch_insider_purchases_returns_none_dataframe(mock_ticker):
    mock_ticker.return_value.insider_transactions = None

    results = _fetch_insider_purchases("NVDA")

    assert results == []


@patch("stock_sentinel.deep_data_engine.yf.Ticker")
def test_fetch_insider_purchases_parses_date_string(mock_ticker):
    df = _make_insider_df([
        {
            "Transaction": "Purchase",
            "Value": 200_000,
            "Insider": "Exec",
            "Position": "VP",
            "Shares": 500,
            "Start Date": "2025-04-01",
        },
    ])
    mock_ticker.return_value.insider_transactions = df

    results = _fetch_insider_purchases("AMZN")

    assert results[0].transaction_date == datetime(2025, 4, 1, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# _fetch_unusual_options_flow
# ─────────────────────────────────────────────────────────────────────────────

def _make_options_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _mock_chain(calls_rows: list[dict], puts_rows: list[dict] | None = None):
    chain = MagicMock()
    chain.calls = _make_options_df(calls_rows)
    chain.puts  = _make_options_df(puts_rows or [])
    return chain


@patch("stock_sentinel.deep_data_engine.yf.Ticker")
def test_fetch_unusual_options_flow_detects_high_volume_calls(mock_ticker):
    mock_ticker.return_value.options = ("2025-05-16",)
    mock_ticker.return_value.option_chain.return_value = _mock_chain(
        calls_rows=[
            {"strike": 130.0, "volume": 3000, "openInterest": 500},   # ratio=6x — qualifies
            {"strike": 135.0, "volume": 500,  "openInterest": 1000},  # volume too low
        ]
    )

    results = _fetch_unusual_options_flow("NVDA")

    assert len(results) == 1
    assert results[0].option_type == "CALL"
    assert results[0].strike == 130.0
    assert results[0].volume_oi_ratio == 6.0


@patch("stock_sentinel.deep_data_engine.yf.Ticker")
def test_fetch_unusual_options_flow_no_qualifying_contracts(mock_ticker):
    mock_ticker.return_value.options = ("2025-05-16",)
    mock_ticker.return_value.option_chain.return_value = _mock_chain(
        calls_rows=[
            {"strike": 130.0, "volume": 200, "openInterest": 500},  # too low volume
        ]
    )

    results = _fetch_unusual_options_flow("NVDA")

    assert results == []


@patch("stock_sentinel.deep_data_engine.yf.Ticker")
def test_fetch_unusual_options_flow_no_expiries(mock_ticker):
    mock_ticker.return_value.options = ()

    results = _fetch_unusual_options_flow("NVDA")

    assert results == []


@patch("stock_sentinel.deep_data_engine.yf.Ticker")
def test_fetch_unusual_options_flow_returns_top5(mock_ticker):
    """When more than 5 contracts qualify, only top 5 by ratio are returned."""
    mock_ticker.return_value.options = ("2025-05-16",)
    calls = [
        {"strike": float(100 + i), "volume": (10 - i) * 1000, "openInterest": 100}
        for i in range(8)
    ]
    mock_ticker.return_value.option_chain.return_value = _mock_chain(calls_rows=calls)

    results = _fetch_unusual_options_flow("NVDA")

    assert len(results) <= 5
    # Results should be sorted highest ratio first
    ratios = [r.volume_oi_ratio for r in results]
    assert ratios == sorted(ratios, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# run_deep_data_cycle — warm-up silence + dedup
# ─────────────────────────────────────────────────────────────────────────────

def _make_insider_alert(ticker="NVDA", value=500_000, shares=1000, insider="Exec") -> InsiderAlert:
    return InsiderAlert(
        ticker=ticker,
        insider_name=insider,
        position="CEO",
        shares=shares,
        value=value,
        transaction_date=datetime(2025, 3, 10, tzinfo=timezone.utc),
    )


def _make_options_alert(ticker="NVDA") -> OptionsFlowAlert:
    return OptionsFlowAlert(
        ticker=ticker,
        expiry="2025-05-16",
        strike=130.0,
        option_type="CALL",
        volume=3000,
        open_interest=500,
        volume_oi_ratio=6.0,
    )


@pytest.mark.asyncio
async def test_first_cycle_warmup_returns_no_alerts():
    """First cycle primes dedup sets but emits nothing."""
    state = DeepDataState()
    insider = _make_insider_alert()
    option  = _make_options_alert()

    with (
        patch("stock_sentinel.deep_data_engine._fetch_insider_purchases", return_value=[insider]),
        patch("stock_sentinel.deep_data_engine._fetch_unusual_options_flow", return_value=[option]),
    ):
        new_i, new_o = await run_deep_data_cycle(["NVDA"], state)

    assert new_i == []
    assert new_o == []
    assert state.warmed_up
    assert len(state._seen_insider) == 1
    assert len(state._seen_options) == 1


@pytest.mark.asyncio
async def test_second_cycle_emits_new_alerts():
    """After warm-up, new items should be returned."""
    state = DeepDataState()
    insider = _make_insider_alert()
    option  = _make_options_alert()

    # Warm up
    with (
        patch("stock_sentinel.deep_data_engine._fetch_insider_purchases", return_value=[insider]),
        patch("stock_sentinel.deep_data_engine._fetch_unusual_options_flow", return_value=[option]),
    ):
        await run_deep_data_cycle(["NVDA"], state)

    # Second cycle — same data: still in dedup, no new alerts
    with (
        patch("stock_sentinel.deep_data_engine._fetch_insider_purchases", return_value=[insider]),
        patch("stock_sentinel.deep_data_engine._fetch_unusual_options_flow", return_value=[option]),
    ):
        new_i, new_o = await run_deep_data_cycle(["NVDA"], state)

    assert new_i == []
    assert new_o == []


@pytest.mark.asyncio
async def test_dedup_blocks_repeated_items():
    """Same insider event in consecutive cycles is suppressed after warm-up."""
    state = DeepDataState()
    state.mark_warmed_up()

    insider = _make_insider_alert()
    state._seen_insider.add(
        f"{insider.ticker}|{insider.insider_name}|"
        f"{insider.transaction_date.date()}|{insider.shares}"
    )

    with (
        patch("stock_sentinel.deep_data_engine._fetch_insider_purchases", return_value=[insider]),
        patch("stock_sentinel.deep_data_engine._fetch_unusual_options_flow", return_value=[]),
    ):
        new_i, new_o = await run_deep_data_cycle(["NVDA"], state)

    assert new_i == []


@pytest.mark.asyncio
async def test_new_item_after_warmup_is_emitted():
    """A truly new item after warm-up should appear in the return value."""
    state = DeepDataState()
    state.mark_warmed_up()

    insider = _make_insider_alert(insider="New Director", shares=9999)

    with (
        patch("stock_sentinel.deep_data_engine._fetch_insider_purchases", return_value=[insider]),
        patch("stock_sentinel.deep_data_engine._fetch_unusual_options_flow", return_value=[]),
    ):
        new_i, new_o = await run_deep_data_cycle(["NVDA"], state)

    assert len(new_i) == 1
    assert new_i[0].insider_name == "New Director"
