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
    """Patch the module's path constants directly so the test is
    immune to import-cache pollution from earlier tests."""
    from runtime.portfolio import slippage_tracker as slip
    test_file = tmp_path / "slippage.jsonl"
    monkeypatch.setattr(slip, "DATA_DIR", tmp_path)
    monkeypatch.setattr(slip, "SLIP_FILE", test_file)

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
        assert test_file.exists(), f"expected {test_file} written"
        roll = await tr.by_strategy(lookback_days=30)
        assert "goat" in roll, f"roll keys = {list(roll.keys())}"
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


# ── Out-of-scope finisher tests ─────────────────────────────────

def test_order_preview_validates_inputs():
    from runtime.portfolio.order_preview import preview_order
    async def go():
        # Limit order without limit_price should reject
        try:
            await preview_order(symbol="NVDA", side="buy", qty=100,
                                order_type="limit")
            raise AssertionError("expected ValueError on missing limit_price")
        except ValueError:
            pass
    asyncio.run(go())


def test_order_preview_market_buy(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in [
        "runtime.portfolio.order_preview",
        "runtime.portfolio.risk_governor",
        "runtime.portfolio.drawdown_bucket",
        "runtime.portfolio.position_risk_state",
        "runtime.portfolio.tax_compliance",
        "runtime.portfolio.tax_lot_ledger",
        "runtime.portfolio.trade_cost_ledger",
    ]:
        sys.modules.pop(mod, None)
    from runtime.portfolio.order_preview import preview_order

    async def go():
        result = await preview_order(
            symbol="NVDA", side="buy", qty=100, order_type="market",
            broker="ibkr", account_id="DU1", strategy_tag="goat",
        )
        assert result["is_preview_only"] is True
        assert result["submission_blocked"] is True
        # Should never have a 'submitted' flag, ever
        assert "submitted" not in result
        # IBKR payload should be present
        assert "ibkr" in result["submission_payloads"]
        assert "IS_PREVIEW_ONLY" in result["submission_payloads"]["ibkr"]
        # All payloads carry the preview-only sentinel
        for broker, payload in result["submission_payloads"].items():
            if broker == "note":
                continue
            assert "IS_PREVIEW_ONLY" in payload

    asyncio.run(go())


def test_order_preview_rejected_governor(tmp_path, monkeypatch):
    """Sized over the heat cap, the governor should reject."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in [
        "runtime.portfolio.order_preview",
        "runtime.portfolio.risk_governor",
        "runtime.portfolio.drawdown_bucket",
        "runtime.portfolio.position_risk_state",
        "runtime.portfolio.tax_compliance",
        "runtime.portfolio.tax_lot_ledger",
        "runtime.portfolio.trade_cost_ledger",
    ]:
        sys.modules.pop(mod, None)
    from runtime.portfolio.order_preview import preview_order
    from runtime.portfolio.drawdown_bucket import get_drawdown_bucket

    async def go():
        # Reset drawdown to green
        bucket = await get_drawdown_bucket()
        await bucket.set_manual_peak(None, note="")
        await bucket.compute(100000.0)
        # 50K R proposal — over the 10% total cap at NAV 100K (10K)
        result = await preview_order(
            symbol="NVDA", side="buy", qty=100,
            strategy_tag="goat", broker="ibkr",
            estimated_R_dollars=50000.0,
        )
        assert result["is_preview_only"] is True
        gov = result.get("governor_decision")
        assert gov is not None
        assert gov["approved"] is False
        # The warnings array should call out the rejection
        assert any("REJECTED" in w for w in result["warnings"])

    asyncio.run(go())


def test_backtest_replay_empty_window(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in [
        "runtime.portfolio.backtest_harness",
        "runtime.portfolio.risk_governor",
        "runtime.portfolio.drawdown_bucket",
    ]:
        sys.modules.pop(mod, None)
    from runtime.portfolio.backtest_harness import replay_window

    async def go():
        # No ideas file -> graceful empty
        out = await replay_window(lookback_days=30)
        assert out["period"]["n_ideas"] == 0

    asyncio.run(go())


def test_manual_adapter_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in ["runtime.portfolio.manual_adapter"]:
        sys.modules.pop(mod, None)
    from runtime.portfolio.manual_adapter import ManualAdapter

    async def go():
        m = ManualAdapter()
        await m.connect()
        assert m.is_connected() is True
        # Empty file -> empty cache
        positions = await m.fetch_positions()
        assert positions == []
        # Add a BTC cold-storage position
        await m.add_position({
            "symbol": "BTC", "account_id": "cold-1",
            "quantity": 0.5, "avg_cost": 45000.0, "current_price": 90000.0,
            "asset_class": "crypto", "currency": "USD",
        })
        positions = await m.fetch_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "BTC"
        # Quote fetch returns empty (no feed)
        quotes = await m.fetch_quotes(["BTC"])
        assert quotes == {}
        # Health reports correctly
        h = m.health()
        assert h["connected"] is True
        assert h["positions_cached"] == 1
        # Remove
        n = await m.remove_position("BTC")
        assert n == 1
        positions = await m.fetch_positions()
        assert positions == []

    asyncio.run(go())


def test_quote_source_static_override():
    from runtime.portfolio.quote_source import StaticOverrideSource

    async def go():
        src = StaticOverrideSource({"NVDA": 185.50, "AAPL": 200.0})
        assert await src.get("NVDA") == 185.50
        assert await src.get("nvda") == 185.50  # case-insensitive
        assert await src.get("UNKNOWN") is None

    asyncio.run(go())


def test_quote_source_chain_falls_through():
    from runtime.portfolio.quote_source import QuoteChain, StaticOverrideSource

    async def go():
        # First source has NVDA but not AAPL; second has AAPL
        chain = QuoteChain([
            StaticOverrideSource({"NVDA": 185.0}),
            StaticOverrideSource({"AAPL": 200.0}),
        ])
        assert await chain.get("NVDA") == 185.0
        assert chain.last_source["NVDA"] == "static_override"
        assert await chain.get("AAPL") == 200.0
        assert await chain.get("MISSING") is None
        assert chain.miss_count["MISSING"] == 1

    asyncio.run(go())


# ── Wave 14K Auto-Trader Phase 1 tests ─────────────────────────

def test_auto_trader_state_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import state as at_state

    async def go():
        # Force reload to pick up tmp_path
        at_state._STATE = None
        s = await at_state.get_state()
        assert s.active is False  # default OFF
        assert await at_state.is_active() is False
        # Resume -> active, no pause
        s = await at_state.resume()
        assert s.active is True
        assert s.paused_by is None
        assert await at_state.is_active() is True
        # Pause by operator
        s = await at_state.pause("test", by="operator")
        assert s.paused_by == "operator"
        assert s.pause_reason == "test"
        assert await at_state.is_active() is False
        # Drawdown halt — even if active, is_active=False
        await at_state.resume()
        s = await at_state.set_drawdown_halt(True, band="halt")
        assert s.drawdown_halt_pause is True
        assert s.drawdown_halt_band == "halt"
        assert await at_state.is_active() is False
        # Drawdown clears
        s = await at_state.set_drawdown_halt(False, band="green")
        assert s.drawdown_halt_pause is False
        assert await at_state.is_active() is True

    asyncio.run(go())


def test_auto_trader_policy_load_and_patch(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import policy as at_policy

    async def go():
        at_policy._POLICY = None
        p = await at_policy.get_policy()
        # Capture BEFORE patch — singleton means p and p2 share the same
        # object and .revision will mutate
        starting_rev = p.revision
        assert starting_rev >= 1
        assert p.min_R_R_ratio == 1.5
        # Patch
        p2 = await at_policy.update_policy(
            {"min_R_R_ratio": 2.0, "max_opens_per_day": 20},
            updated_by="test",
        )
        assert p2.min_R_R_ratio == 2.0
        assert p2.max_opens_per_day == 20
        assert p2.revision == starting_rev + 1
        # Unknown field rejected
        try:
            await at_policy.update_policy({"foo_bar_baz": 99})
            raise AssertionError("expected ValueError on unknown field")
        except ValueError:
            pass

    asyncio.run(go())


def test_auto_open_eligible_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import policy as at_policy

    async def go():
        at_policy._POLICY = None
        idea = {
            "trade_idea_id": "abc123",
            "ticker": "NVDA",
            "type": "stock",
            "strategy_tag": "goat",
            "thesis": "Blackwell ramp + AI capex re-acceleration",
            "entry_price": 180.0,
            "stop_price": 170.0,
            "target_price": 220.0,
            "R_per_share": 10.0,
            "stop_type": "atr",
            "sources": ["sig_001"],
            "rotation_stance": "with_trend",
            "breadth_veto": {"vetoed": False, "reason": "Breadth OK"},
        }
        gov = {"approved": True, "band": "green", "sizing_multiplier": 1.0,
               "reasons": ["approved"]}
        eligible, reason = await at_policy.auto_open_eligible(idea, gov)
        assert eligible is True, reason

    asyncio.run(go())


def test_auto_open_eligible_governor_reject(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import policy as at_policy

    async def go():
        at_policy._POLICY = None
        idea = {
            "trade_idea_id": "x",
            "ticker": "T",
            "thesis": "x x x x x x x x x x x x x x x x x x x x x",
            "entry_price": 100,
            "stop_price": 95,
            "target_price": 115,
            "R_per_share": 5,
            "stop_type": "price",
            "sources": ["s1"],
        }
        gov = {"approved": False, "band": "halt",
               "reasons": ["Drawdown band=halt"]}
        eligible, reason = await at_policy.auto_open_eligible(idea, gov)
        assert eligible is False
        assert "governor" in reason.lower()

    asyncio.run(go())


def test_auto_open_eligible_breadth_veto(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import policy as at_policy

    async def go():
        at_policy._POLICY = None
        idea = {
            "ticker": "T", "thesis": "x" * 30,
            "entry_price": 100, "stop_price": 95, "target_price": 115,
            "R_per_share": 5, "stop_type": "price", "sources": ["s1"],
            "breadth_veto": {"vetoed": True, "reason": "Breadth 30%"},
        }
        gov = {"approved": True, "band": "green"}
        eligible, reason = await at_policy.auto_open_eligible(idea, gov)
        assert eligible is False
        assert "breadth" in reason.lower()

    asyncio.run(go())


def test_auto_open_eligible_rr_too_low(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import policy as at_policy

    async def go():
        at_policy._POLICY = None
        # Entry 100, stop 95, target 105 -> R:R = 1.0 (below 1.5 default)
        idea = {
            "ticker": "T", "thesis": "x" * 30,
            "entry_price": 100, "stop_price": 95, "target_price": 105,
            "R_per_share": 5, "stop_type": "price", "sources": ["s1"],
        }
        gov = {"approved": True, "band": "green"}
        eligible, reason = await at_policy.auto_open_eligible(idea, gov)
        assert eligible is False
        assert "R:R" in reason

    asyncio.run(go())


def test_auto_open_eligible_counter_trend_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import policy as at_policy

    async def go():
        at_policy._POLICY = None
        # Default policy.allow_counter_trend = False
        idea = {
            "ticker": "XLE", "thesis": "x" * 30,
            "entry_price": 90, "stop_price": 86, "target_price": 100,
            "R_per_share": 4, "stop_type": "price", "sources": ["s1"],
            "rotation_stance": "counter_trend",
        }
        gov = {"approved": True, "band": "green"}
        eligible, reason = await at_policy.auto_open_eligible(idea, gov)
        assert eligible is False
        assert "counter-trend" in reason.lower()

    asyncio.run(go())


def test_auto_trader_loop_idea_to_payload():
    """K1b: trade_idea_id stitched into paper_trade.scanner_data so
    Phase 3 outcome attribution can find the originating idea."""
    from runtime.portfolio.auto_trader.loop import _idea_to_paper_payload
    idea = {
        "trade_idea_id": "aaa111",
        "ticker": "NVDA",
        "direction": "long",
        "type": "stock",
        "strategy_tag": "goat",
        "thesis": "Blackwell + AI capex",
        "entry_price": 180.0,
        "stop_price": 170.0,
        "target_price": 220.0,
        "R_per_share": 10.0,
        "stop_type": "atr",
        "stop_basis": "2x ATR below 50d SMA",
        "target_basis": "prior swing high",
        "sources": ["sig_1", "sig_2"],
        "issued_at_iso": "2026-05-26T10:00:00+00:00",
        "rotation_quadrant": "Leading",
        "rotation_stance": "with_trend",
        "confidence_pct": 70,
    }
    payload = _idea_to_paper_payload(idea, qty=50)
    assert payload["symbol"] == "NVDA"
    assert payload["entry_price"] == 180.0
    assert payload["stop_loss"] == 170.0
    assert payload["target_1"] == 220.0
    assert payload["quantity"] == 50
    assert payload["strategy"] == "goat"
    # K1b critical assertion: trade_idea_id round-trips into scanner_data
    assert payload["scanner_data"]["trade_idea_id"] == "aaa111"
    assert payload["scanner_data"]["sources"] == ["sig_1", "sig_2"]
    assert payload["scanner_data"]["rotation_stance"] == "with_trend"
    assert payload["scanner_data"]["R_per_share_at_emit"] == 10.0


def test_outcome_attributor_trigger_mapping():
    """K2b: PaperTradingEngine trigger names → tracker outcome enum."""
    from runtime.portfolio.auto_trader.outcome_attributor import trigger_to_outcome
    assert trigger_to_outcome("stop_hit") == "stopped_out"
    assert trigger_to_outcome("target_hit") == "target_hit"
    assert trigger_to_outcome("trailing_stop") == "manually_closed"
    assert trigger_to_outcome("time_exit") == "expired"
    assert trigger_to_outcome("manual") == "manually_closed"
    # Unknown defaults safely
    assert trigger_to_outcome("unknown_trigger_xxx") == "manually_closed"
    assert trigger_to_outcome("") == "manually_closed"


def test_strategy_bandit_record_and_posterior(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader.strategy_bandit"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import strategy_bandit as sb

    async def go():
        sb._BANDIT = None
        bandit = await sb.get_bandit()
        # Fresh strategy: prior Beta(1, 1) -> mean 0.5
        await bandit.record_result("goat", win=True, R_multiple=2.0)
        await bandit.record_result("goat", win=True, R_multiple=1.5)
        await bandit.record_result("goat", win=False, R_multiple=-1.0)
        p = await bandit.posterior("goat")
        # Beta(3, 2): mean = 3/5 = 0.6
        assert p["alpha"] == 3
        assert p["beta"] == 2
        assert abs(p["mean"] - 0.6) < 1e-6
        assert p["n_observed"] == 3
        assert p["n_wins"] == 2
        assert p["n_losses"] == 1
        # CI is reasonable
        assert 0 <= p["ci_low_95"] < p["mean"] < p["ci_high_95"] <= 1.0
        # Sum R-multiple = 2.0 + 1.5 + (-1.0) = 2.5
        assert abs(p["sum_R_multiple"] - 2.5) < 1e-6

    asyncio.run(go())


def test_strategy_bandit_thompson_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader.strategy_bandit"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import strategy_bandit as sb

    async def go():
        sb._BANDIT = None
        bandit = await sb.get_bandit()
        # Give "goat" a strong winning record; "bravo" mediocre
        for _ in range(20):
            await bandit.record_result("goat", win=True, R_multiple=2.0)
        for _ in range(20):
            await bandit.record_result("bravo", win=False, R_multiple=-1.0)
        # Thompson sample 100x; goat should dominate
        import random
        random.seed(42)  # determinism for the test
        picks = []
        for _ in range(100):
            pick = await bandit.sample_arm(["goat", "bravo"])
            picks.append(pick)
        goat_share = picks.count("goat") / 100
        # With α=21,β=1 vs α=1,β=21, goat should win >95% of the time
        assert goat_share > 0.9, f"goat picked only {goat_share:.0%} of the time"

    asyncio.run(go())


def test_strategy_bandit_ranked_by_lcb(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader.strategy_bandit"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import strategy_bandit as sb

    async def go():
        sb._BANDIT = None
        bandit = await sb.get_bandit()
        # goat: 8W 2L (mean 0.8, narrow CI)
        for _ in range(8):
            await bandit.record_result("goat", win=True, R_multiple=2.0)
        for _ in range(2):
            await bandit.record_result("goat", win=False, R_multiple=-1.0)
        # bravo: 1W 1L (mean 0.5, WIDE CI — small sample)
        await bandit.record_result("bravo", win=True, R_multiple=2.0)
        await bandit.record_result("bravo", win=False, R_multiple=-1.0)
        # newcomer: prior Beta(1,1), n=0
        ranked = await bandit.ranked_by_credible_lower_bound(
            candidates=["goat", "bravo", "newcomer"]
        )
        # goat should be first (highest LCB)
        assert ranked[0]["strategy"] == "goat"
        # newcomer + bravo are weak; both LCB very low
        assert ranked[0]["lcb"] > ranked[-1]["lcb"]

    asyncio.run(go())


def test_shap_attribution_computation():
    """K3d: synthetic close history should surface the right predictors."""
    from runtime.portfolio.auto_trader.shap_attribution import _compute_attributions
    # Construct rows where rotation_aligned==True wins 80%, ==False wins 20%
    rows = []
    for i in range(10):
        rows.append({
            "features": {"rotation_aligned": "True", "sector_etf": "XLK"},
            "win": i < 8,   # 8 wins out of 10
            "R_multiple": 2.0 if i < 8 else -1.0,
        })
    for i in range(10):
        rows.append({
            "features": {"rotation_aligned": "False", "sector_etf": "XLE"},
            "win": i < 2,   # 2 wins out of 10
            "R_multiple": 2.0 if i < 2 else -1.0,
        })
    attr = _compute_attributions(rows, min_samples=3)
    assert attr["n"] == 20
    assert abs(attr["overall_hit_rate"] - 0.5) < 1e-6  # 10/20
    # Top positive should be rotation_aligned=True (or sector_etf=XLK)
    pos_features = [(e["feature"], e["value"]) for e in attr["top_positive"]]
    assert ("rotation_aligned", "True") in pos_features or ("sector_etf", "XLK") in pos_features
    # Top negative should be the opposite
    neg_features = [(e["feature"], e["value"]) for e in attr["top_negative"]]
    assert ("rotation_aligned", "False") in neg_features or ("sector_etf", "XLE") in neg_features


def test_shap_attribution_buckets():
    """Helpers bucket correctly."""
    from runtime.portfolio.auto_trader.shap_attribution import (
        _bucket_days_held, _bucket_hour_utc,
    )
    assert _bucket_days_held(0.5) == "intraday"
    assert _bucket_days_held(2) == "1-3d"
    assert _bucket_days_held(5) == "4-7d"
    assert _bucket_days_held(15) == "8-30d"
    assert _bucket_days_held(45) == "30d+"
    assert _bucket_days_held(None) == "unknown"
    # Hours: 14 UTC ≈ 10 ET = open-hour
    assert _bucket_hour_utc("2026-05-26T14:00:00+00:00") in (
        "open-hour", "midday"  # depends on minute boundary
    )
    assert _bucket_hour_utc(None) == "unknown"


def test_outcome_attributor_extract_trade_idea_id():
    """K2b: trade_idea_id must round-trip via scanner_data."""
    from runtime.portfolio.auto_trader.outcome_attributor import extract_trade_idea_id

    class FakePaperTrade:
        scanner_data = {"trade_idea_id": "abc123", "source": "brief"}

    assert extract_trade_idea_id(FakePaperTrade()) == "abc123"

    class FakePaperTradeNoIdea:
        scanner_data = {"source": "brief"}  # no trade_idea_id

    assert extract_trade_idea_id(FakePaperTradeNoIdea()) is None

    class FakePaperTradeEmpty:
        scanner_data = {}

    assert extract_trade_idea_id(FakePaperTradeEmpty()) is None
    assert extract_trade_idea_id(None) is None


def test_auto_trader_market_open_classifier():
    """The loop picks cadence by market-hours; sanity-check the helper
    even though the gates are governor/drawdown not market-hours."""
    from runtime.portfolio.auto_trader.loop import _is_market_open
    from datetime import datetime, timezone
    # Saturday -> closed
    sat_noon_utc = datetime(2026, 5, 30, 14, 0, tzinfo=timezone.utc)
    assert _is_market_open(sat_noon_utc) is False


def test_auto_trader_observability_record_and_dedup(tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import observability as obs

    async def go():
        idea = {"ticker": "NVDA", "strategy_tag": "goat", "type": "stock"}
        chain = await obs.record_reasoning_chain(
            trade_idea_id="abc123",
            idea_snapshot=idea,
            governor_decision={"approved": True, "band": "green"},
            policy_check={"eligible": True, "reason": "passed", "policy_rev": 1},
            confidence_pct=72.0,
            effective_R_dollars=1000.0,
            planned_qty=100.0,
            model_meta={"executor_model": "claude-sonnet-4"},
        )
        assert chain["trade_idea_id"] == "abc123"
        assert chain["strategy"] == "goat"
        assert chain["confidence_pct"] == 72.0
        # Dedup — second call returns same chain without writing twice
        chain2 = await obs.record_reasoning_chain(
            trade_idea_id="abc123",
            idea_snapshot=idea,
        )
        assert chain2["trade_idea_id"] == "abc123"
        # Update paper_trade_id link
        ok = await obs.update_paper_trade_id("abc123", "paper_456")
        assert ok is True
        got = await obs.get_reasoning_chain("abc123")
        assert got["paper_trade_id"] == "paper_456"
        # List recent
        recent = await obs.list_recent_chains(limit=10)
        assert len(recent) == 1
        assert recent[0]["trade_idea_id"] == "abc123"

    asyncio.run(go())


def test_streaming_mock_publisher():
    from runtime.portfolio.streaming_scaffold import (
        MockDeltaPublisher, PositionDeltaConsumer, DeltaEvent
    )

    async def go():
        cache = []
        consumer = PositionDeltaConsumer(position_cache=cache)
        pub = MockDeltaPublisher(broker="MOCK")
        pub.subscribe(consumer.on_delta)
        await pub.start()
        # Emit a fill
        await pub.emit_test(
            symbol="NVDA", broker="MOCK", account_id="A1",
            qty_delta=100, new_qty=100, price=185.50,
        )
        assert consumer.deltas_applied == 1
        assert len(cache) == 1
        assert cache[0]["symbol"] == "NVDA"
        assert cache[0]["quantity"] == 100
        # Another delta on same position updates qty
        await pub.emit_test(
            symbol="NVDA", broker="MOCK", account_id="A1",
            qty_delta=-30, new_qty=70, price=186.00,
        )
        assert cache[0]["quantity"] == 70
        assert cache[0]["current_price"] == 186.00
        await pub.stop()

    asyncio.run(go())


# ── Self-research (Wave 14K Phase 5: K4a + K4c + K4d) ─────────────

def test_self_research_cluster_losses():
    """K4c: losing trades cluster by (dim, value); singleton dims skipped."""
    from runtime.portfolio.auto_trader.self_research import _cluster_losses
    losing = [
        # XLE-sector cluster of 3
        {"trade_idea_id": "a", "ticker": "XOM", "R_multiple": -0.8,
         "source": "brief", "sector_etf": "XLE", "stop_type": "atr",
         "rotation_quadrant": "Lagging"},
        {"trade_idea_id": "b", "ticker": "CVX", "R_multiple": -1.0,
         "source": "brief", "sector_etf": "XLE", "stop_type": "atr",
         "rotation_quadrant": "Lagging"},
        {"trade_idea_id": "c", "ticker": "EOG", "R_multiple": -0.5,
         "source": "goat", "sector_etf": "XLE", "stop_type": "price",
         "rotation_quadrant": "Lagging"},
        # XLK isolated loss — should NOT form a cluster (n=1 < MIN_CLUSTER_SIZE=3)
        {"trade_idea_id": "d", "ticker": "NVDA", "R_multiple": -2.0,
         "source": "bravo", "sector_etf": "XLK", "stop_type": "price",
         "rotation_quadrant": "Leading"},
    ]
    clusters = _cluster_losses(losing)
    # XLE-sector cluster definitely surfaces (3 losses)
    sector_clusters = [c for c in clusters if c["feature"] == "sector_etf"]
    assert any(c["value"] == "XLE" and c["n_losses"] == 3 for c in sector_clusters)
    # Lagging-rotation cluster also surfaces (3 losses with rotation=Lagging)
    rotation_clusters = [c for c in clusters if c["feature"] == "rotation_quadrant"]
    assert any(c["value"] == "Lagging" and c["n_losses"] == 3 for c in rotation_clusters)
    # Singleton XLK (n=1) must NOT appear
    assert not any(c["feature"] == "sector_etf" and c["value"] == "XLK" for c in clusters)
    # avgR computed correctly for XLE: (-0.8 + -1.0 + -0.5)/3 = -0.7667
    xle = next(c for c in sector_clusters if c["value"] == "XLE")
    assert abs(xle["avg_R"] - (-0.7667)) < 0.001
    # Sorted by n_losses desc
    assert all(clusters[i]["n_losses"] >= clusters[i + 1]["n_losses"]
               for i in range(len(clusters) - 1))


def test_self_research_phrase_topic():
    """K4c: topic phrasing varies by feature dimension."""
    from runtime.portfolio.auto_trader.self_research import _phrase_topic
    # sector_etf branch
    title, rat = _phrase_topic(
        {"feature": "sector_etf", "value": "XLE", "n_losses": 4, "avg_R": -0.9}
    )
    assert "XLE" in title and "4" in title
    assert "sector" in rat.lower()
    # source branch
    title, rat = _phrase_topic(
        {"feature": "source", "value": "polymarket", "n_losses": 5, "avg_R": -1.2}
    )
    assert "polymarket" in title and "source" in title.lower()
    # stop_type branch
    title, _ = _phrase_topic(
        {"feature": "stop_type", "value": "atr", "n_losses": 3, "avg_R": -0.6}
    )
    assert "atr" in title
    # rotation_quadrant branch
    title, _ = _phrase_topic(
        {"feature": "rotation_quadrant", "value": "Lagging", "n_losses": 3, "avg_R": -0.7}
    )
    assert "Lagging" in title


def test_self_research_brief_context_packet_empty(tmp_path, monkeypatch):
    """K4d: with no bandit data, no SHAP history, no topics → empty string."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import self_research as sr
    from runtime.portfolio.auto_trader import strategy_bandit as sb

    async def go():
        sb._BANDIT = None
        packet = await sr.brief_context_packet()
        # No bandit data + no SHAP history + no topics → empty
        assert packet == "" or len(packet.strip()) == 0

    asyncio.run(go())


def test_self_research_brief_context_packet_with_data(tmp_path, monkeypatch):
    """K4d: with strategies recorded + open topic, packet contains both blocks."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import self_research as sr
    from runtime.portfolio.auto_trader import strategy_bandit as sb
    from dataclasses import asdict

    async def go():
        sb._BANDIT = None
        bandit = await sb.get_bandit()
        # Give goat a record so it surfaces in the packet (need n >= 3)
        for _ in range(5):
            await bandit.record_result("goat", win=True, R_multiple=2.0)
        for _ in range(2):
            await bandit.record_result("goat", win=False, R_multiple=-1.0)
        # Pre-seed one open research topic
        topic = sr.ResearchTopic(
            topic_id="topic:sector_etf=XLE",
            title="Why did 3 XLE-sector trades lose (-0.77R avg)?",
            rationale="Concentrated XLE losses; worth fundamentals dive.",
            cluster_features={"sector_etf": "XLE"},
            n_losses=3, avg_R=-0.77,
            example_trade_idea_ids=["a", "b", "c"],
            status="open", created_at_iso=sr._now_iso(),
        )
        sr._persist_topics([asdict(topic)])
        packet = await sr.brief_context_packet()
        assert "STRATEGY EXPECTANCY" in packet
        assert "goat" in packet
        assert "OPEN RESEARCH TOPICS" in packet
        assert "XLE" in packet

    asyncio.run(go())


def test_self_research_apply_shap_to_authority_learner(tmp_path, monkeypatch):
    """K4a: per-source lifts ≥ threshold push counts into SourceAuthorityLearner."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    monkeypatch.setenv("NCL_SHAP_AUTH_THRESHOLD", "0.10")
    # Override SourceAuthorityLearner with an in-memory recorder so we
    # don't depend on its persistence/snapshot mechanics in the test.
    calls = []

    class FakeLearner:
        async def record(self, source, outcome, *, delta=1.0, notes="", **_):
            calls.append({
                "source": source, "outcome": outcome,
                "delta": delta, "notes": notes,
            })
            return type("S", (), {"hits": 1, "misses": 0, "partials": 0})

    # Reset module + monkey-patch the learner import
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import self_research as sr
    import runtime.feedback.source_authority_learner as sal_mod
    monkeypatch.setattr(sal_mod, "get_learner", lambda: FakeLearner())

    async def go():
        # Synthetic SHAP output with one positive + one negative source lift
        attr = {
            "strategy": "goat",
            "features": {
                "source": [
                    {"value": "polymarket", "n": 8, "lift_vs_overall": -0.25,
                     "hit_rate": 0.25, "avg_R": -1.0},
                    {"value": "brief", "n": 10, "lift_vs_overall": 0.20,
                     "hit_rate": 0.70, "avg_R": 1.5},
                    {"value": "noise", "n": 5, "lift_vs_overall": 0.02,  # below threshold
                     "hit_rate": 0.52, "avg_R": 0.1},
                ],
                "sector_etf": [
                    # Non-'source' feature — should be ignored
                    {"value": "XLK", "n": 7, "lift_vs_overall": 0.30,
                     "hit_rate": 0.80, "avg_R": 2.0},
                ],
            },
        }
        result = await sr.apply_shap_to_authority_learner(attr)
        # 2 adjustments: brief (correct, +0.20) + polymarket (wrong, -0.25)
        # noise dropped (|lift|<0.10), sector_etf row never inspected
        adjustments = result["adjustments"]
        assert len(adjustments) == 2
        sources_seen = {a["source"] for a in adjustments}
        assert sources_seen == {"polymarket", "brief"}
        # Polymarket should be a 'wrong' outcome, brief 'correct'
        outcomes_by_source = {a["source"]: a["outcome"] for a in adjustments}
        assert outcomes_by_source["polymarket"] == "wrong"
        assert outcomes_by_source["brief"] == "correct"
        # Delta computed: int(round(|lift|*n)), capped at n//2+1
        # polymarket: round(0.25*8)=2, cap=8//2+1=5 -> 2
        # brief: round(0.20*10)=2, cap=10//2+1=6 -> 2
        deltas_by_source = {a["source"]: a["delta"] for a in adjustments}
        assert deltas_by_source["polymarket"] == 2
        assert deltas_by_source["brief"] == 2
        # Fake learner received the same calls
        call_sources = {c["source"] for c in calls}
        assert call_sources == {"polymarket", "brief"}

    asyncio.run(go())


def test_self_research_resolve_topic(tmp_path, monkeypatch):
    """K4c: resolve_research_topic moves topic to history."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import self_research as sr
    from dataclasses import asdict

    async def go():
        topic = sr.ResearchTopic(
            topic_id="topic:sector_etf=XLE",
            title="Why did 3 XLE-sector trades lose?",
            rationale="...",
            cluster_features={"sector_etf": "XLE"},
            n_losses=3, avg_R=-0.7,
            example_trade_idea_ids=[],
            status="open", created_at_iso=sr._now_iso(),
        )
        sr._persist_topics([asdict(topic)])
        # Open list contains it
        assert any(t["topic_id"] == "topic:sector_etf=XLE"
                   for t in sr.list_open_research_topics())
        # Resolve
        resolved = await sr.resolve_research_topic(
            "topic:sector_etf=XLE",
            resolution_notes="Pulled out XLE — energy regime broken",
        )
        assert resolved is not None
        assert resolved["status"] == "researched"
        assert resolved["resolution_notes"].startswith("Pulled out XLE")
        # Open list no longer contains it
        assert not any(t["topic_id"] == "topic:sector_etf=XLE"
                       for t in sr.list_open_research_topics())
        # Unknown topic → None
        assert await sr.resolve_research_topic("topic:missing") is None

    asyncio.run(go())


# ── Drift detector (Wave 14K Phase 6: K5a + K5b) ──────────────────

def _isolate_drift(tmp_path, monkeypatch):
    """Helper: drift_detector has module-level Path constants captured at
    first import; tests need explicit re-pointing. Returns the freshly-
    imported module with isolated DATA_DIR/STATE_FILE/EVENTS_FILE."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader.drift_detector"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import drift_detector as dd
    data_dir = tmp_path / "data" / "portfolio" / "auto_trader"
    monkeypatch.setattr(dd, "DATA_DIR", data_dir)
    monkeypatch.setattr(dd, "STATE_FILE", data_dir / "drift_state.json")
    monkeypatch.setattr(dd, "EVENTS_FILE", data_dir / "drift_events.jsonl")
    dd._STATE.clear()
    dd._LOADED = False
    return dd


def test_drift_detector_stable_on_random_5050(tmp_path, monkeypatch):
    """K5a: a 50/50 random win/loss stream stays STABLE."""
    dd = _isolate_drift(tmp_path, monkeypatch)

    async def go():
        # Alternate W/L for 60 trades — no drift
        for i in range(60):
            r = await dd.update("goat", win=bool(i % 2))
        assert r["status"] == dd.STABLE
        assert r["n"] == 60
        # Running mean hovers near 0.5
        assert 0.40 <= r["running_mean"] <= 0.60

    asyncio.run(go())


def test_drift_detector_fires_drift_down_on_losing_streak(tmp_path, monkeypatch):
    """K5a: 30 wins followed by a losing streak fires DRIFT_DOWN."""
    # Lower thresholds for test speed
    monkeypatch.setenv("NCL_DRIFT_PH_LAMBDA", "0.30")
    monkeypatch.setenv("NCL_DRIFT_MIN_N", "10")
    dd = _isolate_drift(tmp_path, monkeypatch)
    # Re-apply env-driven module constants since _isolate_drift was already
    # called with the new env vars; PH_LAMBDA/MIN_N picked up via os.getenv
    # at import time, so we re-set explicitly via setattr for safety.
    monkeypatch.setattr(dd, "PH_LAMBDA", 0.30)
    monkeypatch.setattr(dd, "MIN_N", 10)

    async def go():
        # First 30: heavy wins establish high running mean
        for _ in range(30):
            await dd.update("bravo", win=True)
        # Then 15 straight losses → m_down accumulates → DRIFT_DOWN
        statuses_seen = []
        for _ in range(15):
            r = await dd.update("bravo", win=False)
            statuses_seen.append(r["status"])
        # At some point during the losing streak the signal should fire
        assert dd.DRIFT_DOWN in statuses_seen, (
            f"expected DRIFT_DOWN at some point, got {statuses_seen}"
        )

    asyncio.run(go())


def test_drift_detector_persists_across_reload(tmp_path, monkeypatch):
    """K5a: drift state survives a module reload (warm-start)."""
    dd = _isolate_drift(tmp_path, monkeypatch)

    async def go():
        for _ in range(5):
            await dd.update("goat", win=True)
        # Force re-load from disk by clearing the in-memory cache
        dd._STATE.clear()
        dd._LOADED = False
        state = await dd.get_strategy_state("goat")
        assert state is not None
        assert state["n"] == 5
        assert state["running_mean"] > 0.5

    asyncio.run(go())


def test_drift_detector_reset(tmp_path, monkeypatch):
    """K5a: reset_strategy clears PH state but preserves history."""
    dd = _isolate_drift(tmp_path, monkeypatch)

    async def go():
        for _ in range(10):
            await dd.update("goat", win=True)
        assert (await dd.reset_strategy("goat")) is True
        state = await dd.get_strategy_state("goat")
        assert state is not None
        assert state["n"] == 0  # cleared
        # Unknown strategy reset returns False
        assert (await dd.reset_strategy("never_traded")) is False

    asyncio.run(go())


def test_drift_detector_maybe_auto_pause(tmp_path, monkeypatch):
    """K5b: maybe_auto_pause flips state only on DRIFT_DOWN transition."""
    dd = _isolate_drift(tmp_path, monkeypatch)
    # Also isolate the AutoTraderState file
    from runtime.portfolio.auto_trader import state as st
    state_dir = tmp_path / "data" / "portfolio" / "auto_trader"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(st, "DATA_DIR", state_dir)
    monkeypatch.setattr(st, "STATE_FILE", state_dir / "state.json")
    st._STATE = None  # force re-load against the new STATE_FILE

    async def go():
        # Start the auto-trader active
        await st._update(active=True, paused_by=None, pause_reason="")
        # Simulate a DRIFT_DOWN transition
        drift_result = {
            "status": "DRIFT_DOWN", "transition": True,
            "running_mean": 0.25, "recent_hit_rate": 0.10, "n": 50,
        }
        result = await dd.maybe_auto_pause("goat", drift_result)
        assert result["paused"] is True
        s = await st.get_state()
        assert s.paused_by == "drift_detector"
        assert "DRIFT_DOWN" in s.pause_reason
        # STABLE status doesn't pause
        result2 = await dd.maybe_auto_pause("goat", {"status": "STABLE"})
        assert result2["paused"] is False
        # Non-transition DRIFT_DOWN (already drifting) doesn't re-pause
        result3 = await dd.maybe_auto_pause("goat", {
            "status": "DRIFT_DOWN", "transition": False,
            "running_mean": 0.25, "recent_hit_rate": 0.10, "n": 51,
        })
        assert result3["paused"] is False

    asyncio.run(go())


# ── Graduation gate (Wave 14K Phase 6: K5c) ───────────────────────

def test_graduation_gate_needs_data(tmp_path, monkeypatch):
    """K5c: a strategy with no trades fails on sample size first."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    monkeypatch.setenv("NCL_GRAD_MIN_N", "30")
    monkeypatch.setenv("NCL_GRAD_REQUIRE_CYCLE_OK", "0")  # avoid cycle file dep
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import graduation_gate as gg

    async def go():
        report = await gg.evaluate("never_traded")
        assert report["graduated"] is False
        sample_crit = next(c for c in report["criteria"]
                           if c["name"] == "min_sample_size")
        assert sample_crit["passed"] is False
        assert sample_crit["value"] == 0
        assert "NEEDS DATA" in report["recommendation"]

    asyncio.run(go())


def test_graduation_gate_passes_when_all_criteria_met(tmp_path, monkeypatch):
    """K5c: graduation true when expectancy + bandit + drift all clear."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    monkeypatch.setenv("NCL_GRAD_MIN_N", "5")  # low for test
    monkeypatch.setenv("NCL_GRAD_MIN_HIT_RATE", "0.40")
    monkeypatch.setenv("NCL_GRAD_MIN_PROFIT_FACTOR", "1.0")
    monkeypatch.setenv("NCL_GRAD_MIN_SQN", "0.5")
    monkeypatch.setenv("NCL_GRAD_MIN_EXPECTANCY_R", "0.0")
    monkeypatch.setenv("NCL_GRAD_MIN_LCB_HIT_RATE", "0.20")
    monkeypatch.setenv("NCL_GRAD_REQUIRE_CYCLE_OK", "0")
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio"):
            del sys.modules[mod]
    from runtime.portfolio import trade_idea_tracker as tit
    from runtime.portfolio.auto_trader import (
        graduation_gate as gg, strategy_bandit as sb, drift_detector as dd,
    )

    async def go():
        # Reset all singletons
        tit._TRACKER = None
        sb._BANDIT = None
        dd._STATE.clear()
        dd._LOADED = False
        tracker = await tit.get_trade_idea_tracker()
        # Emit + close 6 winners
        for i in range(6):
            idea = await tracker.record_emission(
                source="brief", strategy="goat", ticker=f"T{i}",
                direction="long", entry_price=100.0, stop_price=95.0,
                target_price=115.0, R_per_share=5.0, planned_qty=10,
            )
            await tracker.update_outcome(
                idea["trade_idea_id"], outcome="target_hit", exit_price=115.0,
            )
        # Emit + close 2 losers
        for i in range(2):
            idea = await tracker.record_emission(
                source="brief", strategy="goat", ticker=f"L{i}",
                direction="long", entry_price=100.0, stop_price=95.0,
                target_price=115.0, R_per_share=5.0, planned_qty=10,
            )
            await tracker.update_outcome(
                idea["trade_idea_id"], outcome="stopped_out", exit_price=95.0,
            )
        # Feed bandit so LCB > 0.20
        bandit = await sb.get_bandit()
        for _ in range(6):
            await bandit.record_result("goat", win=True, R_multiple=3.0)
        for _ in range(2):
            await bandit.record_result("goat", win=False, R_multiple=-1.0)
        report = await gg.evaluate("goat")
        # 6W/2L → hit rate 0.75, PF=9.0/2.0=4.5, expectancy positive
        # All criteria should pass.
        failed = [c["name"] for c in report["criteria"] if not c["passed"]]
        assert not failed, f"unexpected failures: {failed} — report={report}"
        assert report["graduated"] is True
        assert "GRADUATED" in report["recommendation"]
        assert report["readiness_score"] == 1.0

    asyncio.run(go())


def test_graduation_gate_blocks_on_recent_drift(tmp_path, monkeypatch):
    """K5c: recent DRIFT_DOWN signal blocks graduation."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    monkeypatch.setenv("NCL_GRAD_MIN_N", "5")
    monkeypatch.setenv("NCL_GRAD_MIN_HIT_RATE", "0.40")
    monkeypatch.setenv("NCL_GRAD_MIN_PROFIT_FACTOR", "1.0")
    monkeypatch.setenv("NCL_GRAD_MIN_SQN", "0.5")
    monkeypatch.setenv("NCL_GRAD_MIN_EXPECTANCY_R", "0.0")
    monkeypatch.setenv("NCL_GRAD_MIN_LCB_HIT_RATE", "0.20")
    monkeypatch.setenv("NCL_GRAD_REQUIRE_CYCLE_OK", "0")
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import drift_detector as dd
    from runtime.portfolio.auto_trader import graduation_gate as gg

    async def go():
        dd._STATE.clear()
        dd._LOADED = False
        # Inject a recent DRIFT_DOWN by hand-crafting the state
        s = dd.PHState(
            n=50, running_mean=0.4, m_down=0.0, m_up=0.0,
            last_status="DRIFT_DOWN", last_status_iso=dd._now_iso(),
            drift_down_count=1, last_drift_iso=dd._now_iso(),
            last_drift_reason="test injected",
        )
        dd._STATE["goat"] = s
        dd._persist_state()
        report = await gg.evaluate("goat")
        drift_crit = next(c for c in report["criteria"]
                          if c["name"] == "no_recent_drift")
        assert drift_crit["passed"] is False
        assert "DRIFT_DOWN" in drift_crit["reason"]

    asyncio.run(go())


def test_graduation_gate_evaluate_all_summary(tmp_path, monkeypatch):
    """K5c: evaluate_all returns _summary with graduated/failing buckets."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    monkeypatch.setenv("NCL_GRAD_REQUIRE_CYCLE_OK", "0")
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio"):
            del sys.modules[mod]
    from runtime.portfolio import trade_idea_tracker as tit
    from runtime.portfolio.auto_trader import graduation_gate as gg

    async def go():
        tit._TRACKER = None
        tracker = await tit.get_trade_idea_tracker()
        # 3 strategies, all under-sampled — all should fail sample-size
        for strat in ("goat", "bravo", "polymarket"):
            idea = await tracker.record_emission(
                source="brief", strategy=strat, ticker=f"X-{strat}",
                direction="long", entry_price=100.0, stop_price=95.0,
                target_price=115.0, R_per_share=5.0, planned_qty=10,
            )
            await tracker.update_outcome(
                idea["trade_idea_id"], outcome="target_hit", exit_price=115.0,
            )
        report = await gg.evaluate_all()
        assert "_summary" in report
        summary = report["_summary"]
        assert summary["total_strategies"] == 3
        assert set(summary["failing"]) == {"goat", "bravo", "polymarket"}
        assert summary["graduated"] == []

    asyncio.run(go())


# ── Friction profile (Wave 14K Phase 7: K6a + K6b) ────────────────

def _isolate_friction(tmp_path, monkeypatch):
    """Same isolation pattern as _isolate_drift: re-points module-level
    file paths and resets state cache."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader.friction_profile"):
            del sys.modules[mod]
    from runtime.portfolio.auto_trader import friction_profile as fp
    data_dir = tmp_path / "data" / "portfolio" / "auto_trader"
    monkeypatch.setattr(fp, "DATA_DIR", data_dir)
    monkeypatch.setattr(fp, "STATE_FILE", data_dir / "friction_profiles.json")
    monkeypatch.setattr(fp, "CALIB_LOG", data_dir / "friction_calibrations.jsonl")
    fp._STATE.clear()
    fp._LOADED = False
    return fp


def test_friction_default_profile_per_asset_type(tmp_path, monkeypatch):
    """K6a: get_profile creates per-asset-type defaults on first lookup."""
    fp = _isolate_friction(tmp_path, monkeypatch)

    async def go():
        # Stock default — low slippage, no partials
        p_stock = await fp.get_profile("goat", asset_type="stock")
        assert p_stock.slippage_bps == 3.0
        assert p_stock.partial_fill_prob == 0.0
        # Options default — higher slippage, partial-fill enabled
        p_opt = await fp.get_profile("options_strat", asset_type="options")
        assert p_opt.slippage_bps == 50.0
        assert p_opt.partial_fill_prob == 0.05
        assert p_opt.partial_fill_min_pct == 0.30

    asyncio.run(go())


def test_friction_apply_long_adds_adverse_slippage(tmp_path, monkeypatch):
    """K6a: long entries fill HIGHER than the limit (paid more)."""
    fp = _isolate_friction(tmp_path, monkeypatch)

    async def go():
        profile = await fp.get_profile("goat", asset_type="stock")
        # Override to 100 bps for an unambiguous shift
        profile.slippage_bps = 100.0  # 1.00%
        payload = {
            "symbol": "NVDA", "direction": "long", "asset_type": "stock",
            "entry_price": 100.0, "quantity": 50, "scanner_data": {},
        }
        out = fp.apply_friction_to_payload(payload, profile)
        # 100 bps = 1% on a $100 entry = $101 fill (adverse for long)
        assert abs(out["entry_price"] - 101.0) < 1e-6
        # Friction metadata preserved
        fr = out["scanner_data"]["friction"]
        assert fr["applied_bps"] == 100.0
        assert fr["original_entry_price"] == 100.0
        assert fr["original_quantity"] == 50.0
        assert fr["is_partial_fill"] is False

    asyncio.run(go())


def test_friction_apply_short_adds_adverse_slippage_other_way(
    tmp_path, monkeypatch,
):
    """K6a: short entries fill LOWER than the limit (got less)."""
    fp = _isolate_friction(tmp_path, monkeypatch)

    async def go():
        profile = await fp.get_profile("short_strat", asset_type="stock")
        profile.slippage_bps = 50.0  # 0.50%
        payload = {
            "symbol": "QQQ", "direction": "short", "asset_type": "stock",
            "entry_price": 200.0, "quantity": 100, "scanner_data": {},
        }
        out = fp.apply_friction_to_payload(payload, profile)
        # 50 bps = 0.50% on a $200 short = $199 fill (worse for short)
        assert abs(out["entry_price"] - 199.0) < 1e-6

    asyncio.run(go())


def test_friction_apply_partial_fill_when_sampled(tmp_path, monkeypatch):
    """K6a: with partial_fill_prob=1.0, quantity is reduced."""
    fp = _isolate_friction(tmp_path, monkeypatch)

    async def go():
        profile = await fp.get_profile("opts", asset_type="options")
        profile.partial_fill_prob = 1.0  # always partial
        profile.partial_fill_min_pct = 0.50
        profile.slippage_bps = 0.0  # isolate qty test from price test
        payload = {
            "symbol": "AAPL", "direction": "long", "asset_type": "options",
            "entry_price": 5.00, "quantity": 100, "scanner_data": {},
        }
        # Use deterministic rng with seed
        import random as r
        rng = r.Random(42)
        out = fp.apply_friction_to_payload(payload, profile, rng=rng)
        # Quantity should be 50-100 (uniform in [50%, 100%] of 100)
        assert 50 <= out["quantity"] <= 100
        fr = out["scanner_data"]["friction"]
        # Whether is_partial_fill is True depends on if frac < 1.0 sampled
        if out["quantity"] < 100:
            assert fr["is_partial_fill"] is True

    asyncio.run(go())


def test_friction_update_profile_clamps(tmp_path, monkeypatch):
    """K6a: operator override clamps prob/min_pct to [0, 1]."""
    fp = _isolate_friction(tmp_path, monkeypatch)

    async def go():
        p = await fp.update_profile(
            "goat", slippage_bps=15.0,
            partial_fill_prob=2.0,        # over-cap
            partial_fill_min_pct=-0.5,    # under-floor
        )
        assert p.slippage_bps == 15.0
        assert p.partial_fill_prob == 1.0  # clamped to 1
        assert p.partial_fill_min_pct == 0.0  # clamped to 0
        # Round trip via all_profiles
        all_p = await fp.all_profiles()
        assert "goat" in all_p
        assert all_p["goat"]["slippage_bps"] == 15.0

    asyncio.run(go())


def test_friction_bps_diff_signed_correctly():
    """K6a: _bps_diff returns positive for adverse-slippage observations."""
    from runtime.portfolio.auto_trader.friction_profile import _bps_diff
    # Long: paid $101 vs planned $100 → +100 bps adverse
    assert abs(_bps_diff(100.0, 101.0, direction="long") - 100.0) < 1e-3
    # Long: paid $99 vs planned $100 → -100 bps (favorable)
    assert abs(_bps_diff(100.0, 99.0, direction="long") - (-100.0)) < 1e-3
    # Short: filled $99 vs planned $100 → +100 bps adverse
    assert abs(_bps_diff(100.0, 99.0, direction="short") - 100.0) < 1e-3
    # Zero planned → 0
    assert _bps_diff(0, 100, direction="long") == 0.0


def test_friction_maybe_calibrate_skips_off_interval(tmp_path, monkeypatch):
    """K6b: only fires when n_closed % CALIB_EVERY_N == 0."""
    fp = _isolate_friction(tmp_path, monkeypatch)
    monkeypatch.setattr(fp, "CALIB_EVERY_N", 10)

    async def go():
        # n=5 with interval=10 → no calibration
        result = await fp.maybe_calibrate("goat", n_closed=5)
        assert result is None
        # n=0 → no calibration
        result = await fp.maybe_calibrate("goat", n_closed=0)
        assert result is None

    asyncio.run(go())


# ── Phase 8 K7a: circuit breaker integration ─────────────────────

def test_circuit_breaker_opens_after_3_failures(tmp_path, monkeypatch):
    """K7a: standard three-strike pattern. Verifies the auto-trader's
    bound CircuitBreaker behaves as expected when called repeatedly."""
    from runtime.portfolio.hygiene import CircuitBreaker

    async def go():
        cb = CircuitBreaker("test_dep", fail_threshold=3, skip_seconds=60)
        assert cb.is_open() is False
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open() is False  # not yet at threshold
        cb.record_failure()
        assert cb.is_open() is True   # crossed threshold
        # Success resets
        cb.record_success()
        assert cb.is_open() is False

    asyncio.run(go())


# ── Phase 8 K7b: crash-recovery replay ────────────────────────────

def test_crash_recovery_replays_state_from_disk(tmp_path, monkeypatch):
    """K7b: state.json + drift_state.json + friction_profiles.json +
    research_topics.json all survive a simulated process restart."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio.auto_trader"):
            del sys.modules[mod]

    from runtime.portfolio.auto_trader import state as st_mod
    from runtime.portfolio.auto_trader import drift_detector as dd_mod
    from runtime.portfolio.auto_trader import friction_profile as fp_mod
    from runtime.portfolio.auto_trader import self_research as sr_mod

    # Point all modules' DATA_DIRs at the tmp tree
    data_dir = tmp_path / "data" / "portfolio" / "auto_trader"
    for mod_obj, attr_pairs in [
        (st_mod, [("DATA_DIR", data_dir), ("STATE_FILE", data_dir / "state.json")]),
        (dd_mod, [("DATA_DIR", data_dir),
                  ("STATE_FILE", data_dir / "drift_state.json"),
                  ("EVENTS_FILE", data_dir / "drift_events.jsonl")]),
        (fp_mod, [("DATA_DIR", data_dir),
                  ("STATE_FILE", data_dir / "friction_profiles.json"),
                  ("CALIB_LOG", data_dir / "friction_calibrations.jsonl")]),
        (sr_mod, [("DATA_DIR", data_dir),
                  ("TOPICS_FILE", data_dir / "research_topics.json"),
                  ("TOPICS_HISTORY", data_dir / "research_topics_history.jsonl")]),
    ]:
        for attr, val in attr_pairs:
            monkeypatch.setattr(mod_obj, attr, val)

    # Reset all singletons / caches
    st_mod._STATE = None
    dd_mod._STATE.clear()
    dd_mod._LOADED = False
    fp_mod._STATE.clear()
    fp_mod._LOADED = False

    async def populate():
        # 1) Auto-trader state: pause it with a reason
        await st_mod._update(active=True, paused_by="operator",
                             pause_reason="pre-crash test",
                             paused_at_iso=st_mod._now_iso())
        await st_mod.record_tick(evaluated=3, opened=1, rejected=2,
                                  last_seen_id="abc-pre-crash")
        # 2) Drift detector: feed some observations
        for _ in range(10):
            await dd_mod.update("goat", win=True)
        # 3) Friction: override
        await fp_mod.update_profile("goat", slippage_bps=8.5)
        # 4) Research topic: persist one open
        from dataclasses import asdict
        topic = sr_mod.ResearchTopic(
            topic_id="topic:sector_etf=XLE",
            title="Test topic", rationale="for crash recovery",
            cluster_features={"sector_etf": "XLE"},
            n_losses=3, avg_R=-0.5,
            example_trade_idea_ids=["x", "y"],
            status="open", created_at_iso=sr_mod._now_iso(),
        )
        sr_mod._persist_topics([asdict(topic)])

    asyncio.run(populate())

    # SIMULATE CRASH: reset every singleton + cache to force disk reload
    st_mod._STATE = None
    dd_mod._STATE.clear()
    dd_mod._LOADED = False
    fp_mod._STATE.clear()
    fp_mod._LOADED = False

    async def recover_and_check():
        # State recovered with pause + counters
        s = await st_mod.get_state()
        assert s.active is True
        assert s.paused_by == "operator"
        assert s.pause_reason == "pre-crash test"
        # Counters MAY have rolled-over if UTC midnight crossed during
        # test — be tolerant about exact values but verify last_seen
        assert s.last_seen_trade_idea_id == "abc-pre-crash"
        # Drift detector recovered with n=10
        ds = await dd_mod.get_strategy_state("goat")
        assert ds is not None
        assert ds["n"] == 10
        assert ds["running_mean"] > 0.5
        # Friction recovered
        fp = await fp_mod.get_profile("goat")
        assert fp.slippage_bps == 8.5
        # Research topic recovered
        topics = sr_mod.list_open_research_topics()
        assert any(t["topic_id"] == "topic:sector_etf=XLE" for t in topics)

    asyncio.run(recover_and_check())


# ── Phase 8 K7c: full lifecycle integration ───────────────────────

def test_full_lifecycle_integration(tmp_path, monkeypatch):
    """K7c: end-to-end flow exercising every wave-14K module.

    1. trade_idea_tracker.record_emission → idea persisted
    2. trade_idea_tracker.update_outcome("target_hit") → R_multiple computed
    3. bandit.record_result → posterior updates
    4. drift_detector.update → STABLE early on
    5. friction_profile.get + apply_friction_to_payload → entry shifted
    6. self_research._cluster_losses on synthetic losses → cluster surfaces
    7. graduation_gate.evaluate → sample-size failure reason
    Each step verifies the contract the next step depends on, so a
    regression in any module surfaces here even if its own unit test
    passes."""
    monkeypatch.setenv("NCL_BASE", str(tmp_path))
    monkeypatch.setenv("NCL_GRAD_REQUIRE_CYCLE_OK", "0")
    monkeypatch.setenv("NCL_DRIFT_MIN_N", "100")  # don't trigger drift in this test
    for mod in list(sys.modules.keys()):
        if mod.startswith("runtime.portfolio"):
            del sys.modules[mod]

    from runtime.portfolio import trade_idea_tracker as tit
    from runtime.portfolio.auto_trader import (
        strategy_bandit as sb, drift_detector as dd,
        friction_profile as fp, graduation_gate as gg,
        self_research as sr,
    )

    # Isolate modules with file constants
    data_dir = tmp_path / "data" / "portfolio" / "auto_trader"
    monkeypatch.setattr(dd, "DATA_DIR", data_dir)
    monkeypatch.setattr(dd, "STATE_FILE", data_dir / "drift_state.json")
    monkeypatch.setattr(dd, "EVENTS_FILE", data_dir / "drift_events.jsonl")
    monkeypatch.setattr(fp, "DATA_DIR", data_dir)
    monkeypatch.setattr(fp, "STATE_FILE", data_dir / "friction_profiles.json")
    monkeypatch.setattr(fp, "CALIB_LOG", data_dir / "friction_calibrations.jsonl")
    tit._TRACKER = None
    sb._BANDIT = None
    dd._STATE.clear(); dd._LOADED = False
    fp._STATE.clear(); fp._LOADED = False

    async def go():
        tracker = await tit.get_trade_idea_tracker()
        bandit = await sb.get_bandit()
        # STEP 1: emit a trade idea
        idea = await tracker.record_emission(
            source="brief", strategy="goat", ticker="NVDA",
            direction="long", entry_price=100.0, stop_price=95.0,
            target_price=115.0, R_per_share=5.0, planned_qty=20,
        )
        tid = idea["trade_idea_id"]

        # STEP 2: friction injection
        profile = await fp.get_profile("goat", asset_type="stock")
        profile.slippage_bps = 50.0  # 0.50% for unambiguous assertion
        payload = {
            "symbol": "NVDA", "direction": "long", "asset_type": "stock",
            "entry_price": 100.0, "quantity": 20, "scanner_data": {},
        }
        out = fp.apply_friction_to_payload(payload, profile)
        assert abs(out["entry_price"] - 100.5) < 1e-6  # paid 50 bps more

        # STEP 3: close the idea as target_hit
        closed = await tracker.update_outcome(
            tid, outcome="target_hit", exit_price=115.0,
        )
        assert closed is not None
        assert closed["R_multiple"] is not None
        assert closed["R_multiple"] > 0  # win

        # STEP 4: bandit records win
        await bandit.record_result("goat", win=True, R_multiple=closed["R_multiple"])
        p = await bandit.posterior("goat")
        assert p["n_observed"] == 1
        assert p["n_wins"] == 1
        assert p["mean"] > 0.5  # Beta(2, 1) mean is 2/3

        # STEP 5: drift detector — STABLE early
        drift_r = await dd.update("goat", win=True)
        assert drift_r["status"] == "STABLE"  # MIN_N=100, can't fire yet

        # STEP 6: synthetic losing cluster for research topic surfacing
        losing = [
            {"trade_idea_id": f"loss-{i}", "ticker": "XOM",
             "R_multiple": -0.8 - i * 0.1, "source": "brief",
             "sector_etf": "XLE", "stop_type": "atr",
             "rotation_quadrant": "Lagging"}
            for i in range(3)
        ]
        clusters = sr._cluster_losses(losing)
        assert any(c["feature"] == "sector_etf" and c["value"] == "XLE"
                   for c in clusters)

        # STEP 7: graduation evaluation — sample-size failure (only 1 close)
        report = await gg.evaluate("goat")
        sample_crit = next(c for c in report["criteria"]
                           if c["name"] == "min_sample_size")
        assert sample_crit["passed"] is False
        assert report["graduated"] is False

    asyncio.run(go())


def test_self_research_topic_id_stable():
    """K4c: same cluster_features always produce same id (idempotency)."""
    from runtime.portfolio.auto_trader.self_research import _topic_id_from_cluster
    id1 = _topic_id_from_cluster({"sector_etf": "XLE"})
    id2 = _topic_id_from_cluster({"sector_etf": "XLE"})
    assert id1 == id2
    # Different value → different id
    id3 = _topic_id_from_cluster({"sector_etf": "XLK"})
    assert id1 != id3
    # Sort-stable: order of keys doesn't matter
    id_a = _topic_id_from_cluster({"a": "1", "b": "2"})
    id_b = _topic_id_from_cluster({"b": "2", "a": "1"})
    assert id_a == id_b
