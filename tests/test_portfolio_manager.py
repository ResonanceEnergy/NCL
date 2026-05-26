"""
Wave 14J J9a — portfolio subsystem test suite.

Covers the Wave 14J modules built across Phases 1-8. Adapter-level
test mocks are deferred (per-broker; needs ib_insync / moomoo / snaptrade
mock harness). This first cut focuses on pure-function correctness +
async store invariants.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Ensure the runtime package is importable
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


# ── Risk governor (J1a + J1b) ──────────────────────────────────────

def test_risk_governor_strategy_normalization():
    from runtime.portfolio.risk_governor import _normalize_strategy
    assert _normalize_strategy("GOAT") == "goat"
    assert _normalize_strategy("Momentum") == "goat"
    assert _normalize_strategy("bravo") == "bravo"
    assert _normalize_strategy("iron_condor") == "options"
    assert _normalize_strategy("polymarket") == "polymarket"
    assert _normalize_strategy(None) == "unknown"
    assert _normalize_strategy("random_xyz") == "unknown"


# ── Drawdown bucket (J0c) ──────────────────────────────────────────

def test_drawdown_band_classifier():
    from runtime.portfolio.drawdown_bucket import _classify
    assert _classify(0.0) == ("green", 1.00)
    assert _classify(-2.5) == ("green", 1.00)
    assert _classify(-3.0) == ("green", 1.00)
    assert _classify(-3.5) == ("caution", 0.75)
    assert _classify(-7.0) == ("caution", 0.75)
    assert _classify(-7.5) == ("warning", 0.50)
    assert _classify(-12.0) == ("warning", 0.50)
    assert _classify(-12.5) == ("halt", 0.00)


# ── Trade idea tracker (J1d) ───────────────────────────────────────

def test_trade_idea_R_multiple_long():
    from runtime.portfolio.trade_idea_tracker import _compute_R_multiple, TradeIdea
    idea = TradeIdea(
        trade_idea_id="t", source="brief", strategy="goat", ticker="NVDA",
        direction="long", entry_price=180.0, R_per_share=10.0,
    )
    assert _compute_R_multiple(idea, 200.0) == 2.0
    assert _compute_R_multiple(idea, 170.0) == -1.0
    assert _compute_R_multiple(idea, 180.0) == 0.0


def test_trade_idea_R_multiple_short():
    from runtime.portfolio.trade_idea_tracker import _compute_R_multiple, TradeIdea
    idea = TradeIdea(
        trade_idea_id="t", source="brief", strategy="bravo", ticker="AAPL",
        direction="short", entry_price=195.0, R_per_share=7.0,
    )
    # Short: lower exit = profit
    assert _compute_R_multiple(idea, 188.0) == 1.0
    assert _compute_R_multiple(idea, 202.0) == -1.0


# ── Options portfolio (J2a + J2c) ──────────────────────────────────

def test_options_dte_watchlist_skips_longs():
    from runtime.portfolio.options_portfolio import dte_watchlist
    # Long position should NOT appear regardless of DTE
    positions = [
        {"symbol": "NVDA260601P00180000", "quantity": 1, "asset_class": "option"},
    ]
    assert dte_watchlist(positions, threshold=999) == []


def test_options_pin_risk_coercion():
    """The parser returns expiry as either string or date depending
    on the code path. The pin-risk function must handle both."""
    from runtime.portfolio.options_portfolio import _coerce_expiry_date
    assert _coerce_expiry_date("2026-05-29") is not None
    assert _coerce_expiry_date("2026-05-29").weekday() == 4
    # Already a date object
    from datetime import date
    d = date(2026, 5, 29)
    assert _coerce_expiry_date(d) == d


# ── Rotation execution (J3a + J3b + J3c) ───────────────────────────

def test_breadth_veto():
    from runtime.portfolio.rotation_execution import breadth_veto_check
    vetoed, reason = breadth_veto_check(30.0)
    assert vetoed is True
    assert "30.0%" in reason
    vetoed, reason = breadth_veto_check(50.0)
    assert vetoed is False
    vetoed, reason = breadth_veto_check(None)
    assert vetoed is False


def test_classify_stance():
    from runtime.portfolio.rotation_execution import classify_stance
    leading = ["XLK"]
    lagging = ["XLE", "XLP"]
    assert classify_stance("XLK", "long", leading, lagging) == "with_trend"
    assert classify_stance("XLE", "long", leading, lagging) == "counter_trend"
    assert classify_stance("XLE", "short", leading, lagging) == "with_trend"
    assert classify_stance("XLK", "short", leading, lagging) == "counter_trend"
    assert classify_stance("XLV", "long", leading, lagging) == "neutral"


def test_pacing_plan_leading_confirmed():
    from runtime.portfolio.rotation_execution import pacing_plan
    p = pacing_plan("NVDA", "Leading", days_in_quadrant=7)
    assert p["stage_1"]["eligible"] is True
    assert p["stage_2"]["eligible"] is True
    assert p["stage_3"]["eligible"] is False


def test_pacing_plan_lagging():
    from runtime.portfolio.rotation_execution import pacing_plan
    p = pacing_plan("XLE", "Lagging")
    assert p["stage_1"]["eligible"] is False
    assert "COUNTER-TREND" in p["notes"]


# ── Tax compliance (J4c + J4d) ────────────────────────────────────

def test_lt_cliff_scan():
    from runtime.portfolio.tax_compliance import lt_cliff_scan
    today = datetime(2026, 5, 26, tzinfo=timezone.utc)
    # cost_basis 350 days ago -> in (340, 366) window -> flagged
    cb_350 = (today - timedelta(days=350)).date().isoformat()
    # cost_basis 100 days ago -> NOT in window
    cb_100 = (today - timedelta(days=100)).date().isoformat()
    positions = [
        {"symbol": "AAPL", "cost_basis_date": cb_350},
        {"symbol": "TSLA", "cost_basis_date": cb_100},
    ]
    out = lt_cliff_scan(positions, today=today)
    assert len(out) == 1
    assert out[0]["symbol"] == "AAPL"
    assert out[0]["days_held"] == 350


def test_earnings_size_modifier_2d():
    from runtime.portfolio.tax_compliance import earnings_size_modifier
    m = earnings_size_modifier(1)
    assert m.long_premium_mult == 0.5
    assert m.short_premium_mult == 0.5


def test_earnings_size_modifier_none():
    from runtime.portfolio.tax_compliance import earnings_size_modifier
    m = earnings_size_modifier(None)
    assert m.long_premium_mult == 1.0


# ── Polymarket discipline (J6a + J6b + J6c) ───────────────────────

def test_kelly_size_passes_when_no_edge():
    from runtime.portfolio.polymarket_discipline import kelly_size
    r = kelly_size(prob_estimated=0.5, prob_market=0.495, bankroll_usd=10000)
    assert r["side"] == "PASS"


def test_kelly_size_with_edge():
    from runtime.portfolio.polymarket_discipline import kelly_size
    r = kelly_size(prob_estimated=0.65, prob_market=0.50, bankroll_usd=10000,
                   days_to_resolution=30)
    assert r["side"] == "YES"
    assert r["edge"] > 0.10
    assert r["size_usd"] > 0


def test_cluster_id_election():
    from runtime.portfolio.polymarket_discipline import cluster_id_from_metadata
    cid = cluster_id_from_metadata({"title": "Who wins the 2028 presidential election?"})
    assert cid.startswith("election_potus_2028")


def test_liquidity_cap_throttle():
    from runtime.portfolio.polymarket_discipline import liquidity_cap
    r = liquidity_cap(proposed_size_usd=500, orderbook_depth_usd=1000)
    assert r["throttled"] is True
    assert r["approved_size_usd"] == 100.0  # 10% of 1000


def test_liquidity_cap_under():
    from runtime.portfolio.polymarket_discipline import liquidity_cap
    r = liquidity_cap(proposed_size_usd=50, orderbook_depth_usd=1000)
    assert r["throttled"] is False
    assert r["approved_size_usd"] == 50.0


# ── Telemetry (J7b + J7d) ─────────────────────────────────────────

def test_drift_alerts():
    from runtime.portfolio.telemetry import drift_alerts
    summary = {
        "allocation": {
            "by_asset_class": {"equity": 70.0, "options": 5.0, "cash": 25.0},
        }
    }
    target = {
        "by_asset_class": {"equity": 60.0, "options": 10.0, "cash": 30.0},
        "tolerance_pct": 5.0,
    }
    alerts = drift_alerts(summary, target=target)
    # equity 70-60 = +10 (TRIM), options 5-10 = -5 (ADD, on the boundary), cash 25-30 = -5 (ADD)
    actions = {a["bucket"]: a["action"] for a in alerts}
    assert actions.get("equity") == "TRIM"


# ── Hygiene (J8a + J8c) ──────────────────────────────────────────

def test_stale_quote_missing_timestamp():
    from runtime.portfolio.hygiene import stale_quote_check
    p = {"asset_class": "equity"}
    s = stale_quote_check(p)
    assert s["stale_age_seconds"] is None
    assert s["is_stale"] is None


def test_stale_quote_fresh():
    from runtime.portfolio.hygiene import stale_quote_check
    now = datetime.now(timezone.utc)
    p = {"asset_class": "equity", "quote_timestamp": now.isoformat()}
    s = stale_quote_check(p, now=now + timedelta(seconds=10))
    assert s["is_stale"] is False


def test_circuit_breaker_opens_after_threshold():
    from runtime.portfolio.hygiene import CircuitBreaker
    cb = CircuitBreaker("test", fail_threshold=3, skip_seconds=600)
    assert cb.is_open() is False
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open() is False
    cb.record_failure()
    assert cb.is_open() is True
    cb.record_success()
    assert cb.is_open() is False


# ── Trading cost ledger (J0a) ────────────────────────────────────

def test_trade_cost_ledger_async(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    # Force module re-init to pick up the env override
    if "runtime.portfolio.trade_cost_ledger" in sys.modules:
        del sys.modules["runtime.portfolio.trade_cost_ledger"]
    from runtime.portfolio import trade_cost_ledger as tcl

    async def go():
        led = tcl.TradeCostLedger()
        await led.record(
            broker="IBKR", action="commission", amount_usd=0.65,
            symbol="NVDA", asset_class="equity", strategy_tag="goat",
        )
        s = await led.summary_today()
        assert s["total_usd"] == 0.65
        assert s["entries"] == 1
        assert s["by_broker"] == {"IBKR": 0.65}
        assert s["by_strategy"] == {"goat": 0.65}

    asyncio.run(go())


# ── Position risk store (J0b) ────────────────────────────────────

def test_position_risk_store_R_compute(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    if "runtime.portfolio.position_risk_state" in sys.modules:
        del sys.modules["runtime.portfolio.position_risk_state"]
    from runtime.portfolio import position_risk_state as prs

    async def go():
        store = prs.PositionRiskStore()
        r = await store.set(
            broker="IBKR", account_id="DU1", symbol="NVDA",
            qty=100, entry_price=180, stop_price=170,
            stop_type="atr",
        )
        assert r["R_dollars"] == 1000.0
        assert r["risk_status"] == "at_risk"
        assert r["position_key"] == "ibkr:du1:NVDA"

    asyncio.run(go())


# ── Mock adapter harness (Wave 14J finisher) ─────────────────────

def test_mock_adapter_basic_flow():
    from runtime.portfolio.mock_adapter import MockAdapter, make_canned_positions

    async def go():
        m = MockAdapter(
            broker_name="MOCK1",
            canned_positions=make_canned_positions(
                ("NVDA", 100, "MOCK1", "equity", 180.0),
                ("AAPL", 50, "MOCK1", "equity", 200.0),
            ),
        )
        assert m.is_connected() is False
        await m.connect()
        assert m.is_connected() is True
        accounts = await m.fetch_accounts()
        assert len(accounts) == 1
        positions = await m.fetch_positions()
        assert len(positions) == 2
        quotes = await m.fetch_quotes(["NVDA", "AAPL"])
        assert "NVDA" in quotes
        await m.disconnect()
        assert m.is_connected() is False

    asyncio.run(go())


def test_mock_adapter_connect_failure():
    from runtime.portfolio.mock_adapter import MockAdapter, MockBrokerError

    async def go():
        m = MockAdapter(broker_name="BAD", simulate_connect_failure=True)
        try:
            await m.connect()
        except MockBrokerError:
            return
        raise AssertionError("expected MockBrokerError on connect")

    asyncio.run(go())


def test_mock_adapter_quote_failure():
    from runtime.portfolio.mock_adapter import MockAdapter

    async def go():
        m = MockAdapter(broker_name="QUIET", simulate_quote_failure=True)
        await m.connect()
        q = await m.fetch_quotes(["AAPL", "NVDA"])
        assert q == {}

    asyncio.run(go())


def test_mock_adapter_disconnect_after_n():
    from runtime.portfolio.mock_adapter import MockAdapter, MockBrokerError

    async def go():
        m = MockAdapter(broker_name="FLAKY", simulate_disconnect_after_n_calls=2)
        await m.connect()
        # First two calls succeed
        await m.fetch_accounts()
        await m.fetch_positions()
        # Third should error — adapter went disconnected
        assert m.is_connected() is False
        try:
            await m.fetch_positions()
            raise AssertionError("expected error after disconnect")
        except MockBrokerError:
            pass

    asyncio.run(go())


# ── J4b spec-ID lot ledger ─────────────────────────────────────

def test_tax_lot_recommend_hifo(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    if "runtime.portfolio.tax_lot_ledger" in sys.modules:
        del sys.modules["runtime.portfolio.tax_lot_ledger"]
    from runtime.portfolio import tax_lot_ledger as tll

    async def go():
        led = tll.TaxLotLedger()
        await led.record_open(symbol="AAPL", broker="IBKR", account_id="DU1",
                              qty=100, cost_basis_per_share=150.0,
                              acquisition_date="2024-01-15")
        await led.record_open(symbol="AAPL", broker="IBKR", account_id="DU1",
                              qty=50, cost_basis_per_share=210.0,
                              acquisition_date="2025-06-01")
        await led.record_open(symbol="AAPL", broker="IBKR", account_id="DU1",
                              qty=30, cost_basis_per_share=190.0,
                              acquisition_date="2025-11-01")
        rec = await led.recommend_lot_selection(
            symbol="AAPL", qty_to_sell=80, objective="hifo", broker="IBKR",
        )
        # HIFO -> consume 210 first (50 shares), then 190 (30 shares)
        assert rec["qty_satisfied"] == 80
        assert len(rec["selection"]) == 2
        assert rec["selection"][0]["cost_basis_per_share"] == 210.0
        assert rec["selection"][1]["cost_basis_per_share"] == 190.0
        assert "IBKR" in rec["method_hint"]

    asyncio.run(go())


def test_tax_lot_recommend_fifo(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    if "runtime.portfolio.tax_lot_ledger" in sys.modules:
        del sys.modules["runtime.portfolio.tax_lot_ledger"]
    from runtime.portfolio import tax_lot_ledger as tll

    async def go():
        led = tll.TaxLotLedger()
        await led.record_open(symbol="TSLA", broker="IBKR", account_id="DU1",
                              qty=20, cost_basis_per_share=200,
                              acquisition_date="2024-01-01")
        await led.record_open(symbol="TSLA", broker="IBKR", account_id="DU1",
                              qty=20, cost_basis_per_share=300,
                              acquisition_date="2025-01-01")
        rec = await led.recommend_lot_selection(
            symbol="TSLA", qty_to_sell=15, objective="fifo",
        )
        # FIFO -> consume from earlier lot only
        assert rec["selection"][0]["cost_basis_per_share"] == 200
        assert rec["selection"][0]["qty_consumed"] == 15


    asyncio.run(go())


# ── J5a/b/c on-chain journal ───────────────────────────────────

def test_on_chain_journal_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    if "runtime.portfolio.on_chain_journal" in sys.modules:
        del sys.modules["runtime.portfolio.on_chain_journal"]
    from runtime.portfolio import on_chain_journal as ocj

    async def go():
        j = ocj.OnChainJournal()
        await j.record_tx(
            tx_hash="0xabc", chain="ethereum", wallet="0xdead",
            timestamp_iso="2026-05-26T10:00:00+00:00",
            category="buy", asset_symbol="ETH", qty=2.5,
            price_at_block_usd=3000.0,
        )
        # Same tx_hash twice -> dedup, balance not double-counted
        await j.record_tx(
            tx_hash="0xabc", chain="ethereum", wallet="0xdead",
            timestamp_iso="2026-05-26T10:00:00+00:00",
            category="buy", asset_symbol="ETH", qty=2.5,
            price_at_block_usd=3000.0,
        )
        pos = await j.positions_for(wallet="0xdead")
        assert len(pos) == 1
        assert pos[0]["qty"] == 2.5
        assert pos[0]["avg_cost_basis_usd"] == 3000.0

    asyncio.run(go())


def test_on_chain_classify_liquid_stake():
    from runtime.portfolio.on_chain_journal import classify_asset
    c = classify_asset("stETH")
    assert c["is_liquid_staked"] is True
    assert c["underlying_a"] == "ETH"


def test_on_chain_classify_lp():
    from runtime.portfolio.on_chain_journal import classify_asset
    c = classify_asset("UNI-V2-USDC-WETH")
    assert c["is_lp"] is True


def test_on_chain_multichain_rollup(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    if "runtime.portfolio.on_chain_journal" in sys.modules:
        del sys.modules["runtime.portfolio.on_chain_journal"]
    from runtime.portfolio import on_chain_journal as ocj

    async def go():
        j = ocj.OnChainJournal()
        # Same wallet, same symbol (USDC) on 2 chains
        await j.record_tx(tx_hash="t1", chain="ethereum", wallet="0xw",
                          timestamp_iso="2026-05-01T00:00:00+00:00",
                          category="buy", asset_symbol="USDC", qty=1000,
                          price_at_block_usd=1.0)
        await j.record_tx(tx_hash="t2", chain="arbitrum", wallet="0xw",
                          timestamp_iso="2026-05-02T00:00:00+00:00",
                          category="buy", asset_symbol="USDC", qty=500,
                          price_at_block_usd=1.0)
        agg = await j.aggregate_multichain("0xw")
        assert "ethereum" in agg["chains_with_balance"]
        assert "arbitrum" in agg["chains_with_balance"]
        usdc = agg["by_symbol"]["USDC"]
        assert usdc["total_qty"] == 1500.0
        assert usdc["by_chain"]["ethereum"] == 1000.0
        assert usdc["by_chain"]["arbitrum"] == 500.0

    asyncio.run(go())


# ── J7c slippage tracker ───────────────────────────────────────

def test_slippage_arrival_bps_long():
    from runtime.portfolio.slippage_tracker import _compute_arrival_bps
    # buy fill of 100.10 vs arrival 100.00 = +10 bps adverse
    bps = _compute_arrival_bps(100.10, 100.00, "buy")
    assert round(bps, 2) == 10.0


def test_slippage_arrival_bps_short():
    from runtime.portfolio.slippage_tracker import _compute_arrival_bps
    # sell fill of 99.90 vs arrival 100.00 = +10 bps adverse
    bps = _compute_arrival_bps(99.90, 100.00, "sell")
    assert round(bps, 2) == 10.0


def test_slippage_record_and_rollup(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    if "runtime.portfolio.slippage_tracker" in sys.modules:
        del sys.modules["runtime.portfolio.slippage_tracker"]
    from runtime.portfolio import slippage_tracker as slip

    async def go():
        tr = slip.SlippageTracker()
        await tr.record_fill(
            fill_id="f1", symbol="NVDA", side="buy", qty=100,
            fill_price=180.10, arrival_price=180.00,
            vwap_benchmark_price=180.05, strategy="goat",
        )
        await tr.record_fill(
            fill_id="f2", symbol="AAPL", side="buy", qty=50,
            fill_price=200.20, arrival_price=200.00,
            vwap_benchmark_price=200.10, strategy="goat",
        )
        roll = await tr.by_strategy(lookback_days=30)
        assert "goat" in roll
        assert roll["goat"]["n_fills"] == 2
        assert roll["goat"]["arrival_mean_bps"] > 0  # both adverse

    asyncio.run(go())


# ── J8d trade/settle split ─────────────────────────────────────

def test_settle_date_equity_t1():
    from runtime.portfolio.settle_calendar import settle_date
    # 2026-05-26 is Tuesday; equity T+1 -> 2026-05-27
    assert settle_date("equity", "2026-05-26") == "2026-05-27"


def test_settle_date_skips_weekend():
    from runtime.portfolio.settle_calendar import settle_date
    # Friday 2026-05-29 + T+1 -> Monday 2026-06-01
    assert settle_date("equity", "2026-05-29") == "2026-06-01"


def test_settle_date_crypto_t0():
    from runtime.portfolio.settle_calendar import settle_date
    assert settle_date("crypto", "2026-05-26") == "2026-05-26"


def test_cash_view_settled_vs_unsettled():
    from runtime.portfolio.settle_calendar import cash_view
    trades = [
        {"asset_class": "equity", "trade_date": "2026-05-23", "cash_delta": 1000},   # T+1 = 2026-05-26, settled if as_of >= that
        {"asset_class": "equity", "trade_date": "2026-05-26", "cash_delta": -500},  # T+1 = 2026-05-27, unsettled as of 2026-05-26
        {"asset_class": "crypto", "trade_date": "2026-05-26", "cash_delta": 200},   # T+0, settled
    ]
    cv = cash_view(trades, as_of="2026-05-26")
    # equity trade from 2026-05-23 settled on 2026-05-26 (assuming biz day Tuesday)
    assert cv["settled_today"] >= 1000  # at least the first equity + crypto
    # Second equity (-500) unsettled
    assert cv["unsettled_outflow"] == -500
