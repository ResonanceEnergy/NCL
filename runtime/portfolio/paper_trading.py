#!/usr/bin/env python3
"""
Paper Trading Engine for NCL Brain
====================================
Simulated trade tracking with enforced pre-trade planning.
Every trade requires entry price, stop loss, and target BEFORE execution.

Tracks: R-multiples, MAE/MFE, win rate, expectancy, equity curve.
Persistence: JSONL file per trade + summary stats.

Key principles (from professional trading research):
- No trade without a plan (stop + target required)
- Position sizing from stop distance
- Slippage simulation (configurable)
- Time-based exits (max hold period)
- Full trade journal with grades and notes
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger("ncl.portfolio.paper")

# ── Default Configuration ────────────────────────────────────────
DEFAULT_ACCOUNT_BALANCE = 10_000.0  # Match real trading capital
DEFAULT_MAX_RISK_PCT = 2.0  # Max 2% risk per trade
DEFAULT_SLIPPAGE_STOCK = 0.05  # 0.05% slippage for stocks
DEFAULT_SLIPPAGE_OPTION = 0.50  # 0.50% slippage for options
DEFAULT_SLIPPAGE_CRYPTO = 0.10  # 0.10% slippage for crypto
DEFAULT_MAX_HOLD_DAYS = 30  # Auto-flag after 30 days


class PaperTrade:
    """A single paper trade with full lifecycle tracking."""

    def __init__(self, data: Dict[str, Any]):
        # Identity
        self.id: str = data.get("id", str(uuid.uuid4()))
        self.created_at: str = data.get("created_at", datetime.now(timezone.utc).isoformat())

        # Instrument
        self.symbol: str = data["symbol"]
        self.direction: str = data.get("direction", "long")  # long | short
        self.asset_type: str = data.get("asset_type", "stock")  # stock | option | crypto
        self.strategy: str = data.get("strategy", "manual")  # GOAT | BRAVO | manual

        # Entry (REQUIRED)
        self.entry_price: float = data["entry_price"]
        self.quantity: float = data.get("quantity", 0)
        self.entry_date: str = data.get("entry_date", datetime.now(timezone.utc).isoformat())

        # Exit plan (REQUIRED before entry — enforced by API)
        self.stop_loss: float = data["stop_loss"]
        self.target_1: float = data["target_1"]
        self.target_2: float = data.get("target_2", 0)
        self.target_3: float = data.get("target_3", 0)
        self.trailing_stop_pct: float = data.get("trailing_stop_pct", 0)
        self.max_hold_days: int = data.get("max_hold_days", DEFAULT_MAX_HOLD_DAYS)

        # Calculated at entry
        self.risk_per_share: float = abs(self.entry_price - self.stop_loss)
        self.risk_reward_ratio: float = self._calc_rr()
        self.position_risk_dollars: float = self.risk_per_share * abs(self.quantity)
        self.position_risk_pct: float = data.get("position_risk_pct", 0)

        # Current state
        self.status: str = data.get("status", "open")
        # open | closed_target | closed_stop | closed_manual | closed_time | closed_trail
        self.current_price: float = data.get("current_price", self.entry_price)
        self.highest_price: float = data.get("highest_price", self.entry_price)
        self.lowest_price: float = data.get("lowest_price", self.entry_price)
        self.unrealized_pl: float = data.get("unrealized_pl", 0)
        self.unrealized_pl_pct: float = data.get("unrealized_pl_pct", 0)
        self.r_multiple: float = data.get("r_multiple", 0)
        self.mae: float = data.get("mae", 0)  # Max Adverse Excursion (worst drawdown)
        self.mfe: float = data.get("mfe", 0)  # Max Favorable Excursion (best unrealized)
        self.mae_r: float = data.get("mae_r", 0)  # MAE in R-multiples
        self.mfe_r: float = data.get("mfe_r", 0)  # MFE in R-multiples
        self.days_held: int = data.get("days_held", 0)

        # Exit (filled when closed)
        self.exit_price: float = data.get("exit_price", 0)
        self.exit_date: str = data.get("exit_date", "")
        self.exit_reason: str = data.get("exit_reason", "")
        self.realized_pl: float = data.get("realized_pl", 0)
        self.realized_pl_pct: float = data.get("realized_pl_pct", 0)
        self.slippage_applied: float = data.get("slippage_applied", 0)

        # Journal
        self.notes: str = data.get("notes", "")
        self.confidence: int = data.get("confidence", 3)  # 1-5
        self.trade_grade: str = data.get("trade_grade", "")  # A/B/C (post-trade)
        self.rules_followed: bool = data.get("rules_followed", True)
        self.tags: List[str] = data.get("tags", [])

        # Scanner data snapshot (original scanner result that triggered this)
        self.scanner_data: Dict[str, Any] = data.get("scanner_data", {})

        # Price history for tracking
        self.price_history: List[Dict[str, Any]] = data.get("price_history", [])

        # Option-specific fields
        self.option_type: str = data.get("option_type", "")  # call | put
        self.strike_price: float = data.get("strike_price", 0)
        self.expiration: str = data.get("expiration", "")
        self.delta: float = data.get("delta", 0)
        self.theta: float = data.get("theta", 0)
        self.iv: float = data.get("iv", 0)

    def _calc_rr(self) -> float:
        """Calculate risk:reward ratio from entry, stop, target."""
        if self.risk_per_share == 0:
            return 0
        reward = abs(self.target_1 - self.entry_price)
        return round(reward / self.risk_per_share, 2) if self.risk_per_share > 0 else 0

    def update_price(self, price: float) -> Optional[str]:
        """
        Update current price and recalculate all tracking metrics.
        Returns trigger reason if stop/target hit, else None.
        """
        if self.status != "open":
            return None

        self.current_price = price
        trigger = None

        # Track extremes
        if price > self.highest_price:
            self.highest_price = price
        if price < self.lowest_price:
            self.lowest_price = price

        # Calculate P&L
        if self.direction == "long":
            self.unrealized_pl = (price - self.entry_price) * self.quantity
            self.unrealized_pl_pct = ((price - self.entry_price) / self.entry_price) * 100
            # MAE = worst drawdown from entry
            adverse = self.entry_price - self.lowest_price
            self.mae = max(self.mae, adverse * self.quantity)
            # MFE = best gain from entry
            favorable = self.highest_price - self.entry_price
            self.mfe = max(self.mfe, favorable * self.quantity)
        else:  # short
            self.unrealized_pl = (self.entry_price - price) * self.quantity
            self.unrealized_pl_pct = ((self.entry_price - price) / self.entry_price) * 100
            adverse = self.highest_price - self.entry_price
            self.mae = max(self.mae, adverse * self.quantity)
            favorable = self.entry_price - self.lowest_price
            self.mfe = max(self.mfe, favorable * self.quantity)

        # R-multiple
        if self.risk_per_share > 0:
            self.r_multiple = round(self.unrealized_pl / (self.risk_per_share * self.quantity), 2)
            self.mae_r = (
                round(self.mae / (self.risk_per_share * self.quantity), 2) if self.quantity else 0
            )
            self.mfe_r = (
                round(self.mfe / (self.risk_per_share * self.quantity), 2) if self.quantity else 0
            )

        # Days held
        try:
            entry_dt = datetime.fromisoformat(self.entry_date.replace("Z", "+00:00"))
            self.days_held = (datetime.now(timezone.utc) - entry_dt).days
        except Exception:
            pass

        # Check triggers
        if self.direction == "long":
            if price <= self.stop_loss:
                trigger = "stop_hit"
            elif price >= self.target_1:
                trigger = "target_hit"
            # Trailing stop check
            if self.trailing_stop_pct > 0:
                trail_price = self.highest_price * (1 - self.trailing_stop_pct / 100)
                if price <= trail_price and price > self.stop_loss:
                    trigger = "trailing_stop"
        else:  # short
            if price >= self.stop_loss:
                trigger = "stop_hit"
            elif price <= self.target_1:
                trigger = "target_hit"
            if self.trailing_stop_pct > 0:
                trail_price = self.lowest_price * (1 + self.trailing_stop_pct / 100)
                if price >= trail_price and price < self.stop_loss:
                    trigger = "trailing_stop"

        # Time-based exit check
        if self.max_hold_days > 0 and self.days_held >= self.max_hold_days:
            trigger = "time_exit"

        # Record price point
        self.price_history.append(
            {
                "date": datetime.now(timezone.utc).isoformat(),
                "price": price,
                "pl": round(self.unrealized_pl, 2),
                "r": self.r_multiple,
            }
        )

        return trigger

    def close(self, exit_price: float, reason: str, slippage: float = 0) -> None:
        """Close the trade with final price and reason."""
        # Apply slippage (worse fill)
        if self.direction == "long":
            adjusted_price = exit_price * (1 - slippage / 100)
        else:
            adjusted_price = exit_price * (1 + slippage / 100)

        self.exit_price = round(adjusted_price, 4)
        self.exit_date = datetime.now(timezone.utc).isoformat()
        self.exit_reason = reason
        self.slippage_applied = slippage
        self.current_price = adjusted_price

        # Final P&L
        if self.direction == "long":
            self.realized_pl = (adjusted_price - self.entry_price) * self.quantity
        else:
            self.realized_pl = (self.entry_price - adjusted_price) * self.quantity

        cost_basis = self.entry_price * abs(self.quantity)
        self.realized_pl_pct = (self.realized_pl / cost_basis * 100) if cost_basis else 0

        # Final R-multiple
        if self.risk_per_share > 0 and self.quantity:
            self.r_multiple = round(self.realized_pl / (self.risk_per_share * self.quantity), 2)

        # Status
        status_map = {
            "stop_hit": "closed_stop",
            "target_hit": "closed_target",
            "trailing_stop": "closed_trail",
            "time_exit": "closed_time",
            "manual": "closed_manual",
        }
        self.status = status_map.get(reason, "closed_manual")

        # Final extremes update
        if exit_price > self.highest_price:
            self.highest_price = exit_price
        if exit_price < self.lowest_price:
            self.lowest_price = exit_price

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSONL persistence."""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "symbol": self.symbol,
            "direction": self.direction,
            "asset_type": self.asset_type,
            "strategy": self.strategy,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "entry_date": self.entry_date,
            "stop_loss": self.stop_loss,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "target_3": self.target_3,
            "trailing_stop_pct": self.trailing_stop_pct,
            "max_hold_days": self.max_hold_days,
            "risk_per_share": self.risk_per_share,
            "risk_reward_ratio": self.risk_reward_ratio,
            "position_risk_dollars": self.position_risk_dollars,
            "position_risk_pct": self.position_risk_pct,
            "status": self.status,
            "current_price": self.current_price,
            "highest_price": self.highest_price,
            "lowest_price": self.lowest_price,
            "unrealized_pl": round(self.unrealized_pl, 2),
            "unrealized_pl_pct": round(self.unrealized_pl_pct, 2),
            "r_multiple": self.r_multiple,
            "mae": round(self.mae, 2),
            "mfe": round(self.mfe, 2),
            "mae_r": self.mae_r,
            "mfe_r": self.mfe_r,
            "days_held": self.days_held,
            "exit_price": self.exit_price,
            "exit_date": self.exit_date,
            "exit_reason": self.exit_reason,
            "realized_pl": round(self.realized_pl, 2),
            "realized_pl_pct": round(self.realized_pl_pct, 2),
            "slippage_applied": self.slippage_applied,
            "notes": self.notes,
            "confidence": self.confidence,
            "trade_grade": self.trade_grade,
            "rules_followed": self.rules_followed,
            "tags": self.tags,
            "scanner_data": self.scanner_data,
            "price_history": self.price_history[-100:],  # Keep last 100 price points
            "option_type": self.option_type,
            "strike_price": self.strike_price,
            "expiration": self.expiration,
            "delta": self.delta,
            "theta": self.theta,
            "iv": self.iv,
        }

    def to_summary(self) -> Dict[str, Any]:
        """Compact dict for list views (no price_history, no scanner_data)."""
        d = self.to_dict()
        d.pop("price_history", None)
        d.pop("scanner_data", None)
        return d


class PaperTradingEngine:
    """
    Paper trading engine with JSONL persistence and portfolio stats.

    Enforces: entry + stop + target required before trade creation.
    Tracks: R-multiples, MAE/MFE, win rate, expectancy, equity curve.
    """

    def __init__(self, data_dir: Optional[str] = None, account_balance: float = 0):
        base = Path(data_dir) if data_dir else Path(__file__).resolve().parents[2] / "data"
        self._data_dir = base / "paper_trading"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._trades_file = self._data_dir / "trades.jsonl"
        # Wave 14X-5 (2026-05-29): persisted balance so deposits + tracked
        # NAV survive process restarts. Defaults match prior behavior.
        self._balance_file = self._data_dir / "balance.json"
        self._trades: Dict[str, PaperTrade] = {}
        self._account_balance = account_balance or self._load_balance() or DEFAULT_ACCOUNT_BALANCE
        self._load_trades()

    def _load_balance(self) -> float:
        """Wave 14X-5: load persisted balance, 0.0 if none."""
        try:
            if self._balance_file.exists():
                return float(json.loads(self._balance_file.read_text()).get("balance", 0))
        except Exception as e:
            logger.warning("paper balance load failed: %s", e)
        return 0.0

    def _save_balance(self) -> None:
        """Wave 14X-5: persist balance to disk."""
        try:
            self._balance_file.write_text(json.dumps({"balance": self._account_balance}))
        except Exception as e:
            logger.warning("paper balance save failed: %s", e)

    def deposit(self, amount: float, note: str = "") -> float:
        """Wave 14X-5: deposit cash into the paper account (admin op).
        Positive amount credits, negative debits. Persists immediately.
        Returns the new balance.
        """
        self._account_balance += float(amount)
        self._save_balance()
        logger.info(
            "[PAPER] deposit %+.2f -> new balance %.2f (%s)",
            amount, self._account_balance, note or "no note",
        )
        return self._account_balance

    def set_balance(self, amount: float, note: str = "") -> float:
        """Wave 14X-5: set absolute balance (admin op). Persists."""
        self._account_balance = float(amount)
        self._save_balance()
        logger.info(
            "[PAPER] set_balance -> %.2f (%s)",
            self._account_balance, note or "no note",
        )
        return self._account_balance

    @property
    def trades(self) -> Dict[str, "PaperTrade"]:
        """All trades (read-only access)."""
        return self._trades

    @property
    def trade_count(self) -> int:
        return len(self._trades)

    # ── Persistence ───────────────────────────────────────────────

    def _load_trades(self) -> None:
        """Load trades from JSONL file."""
        if not self._trades_file.exists():
            return
        try:
            with open(self._trades_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        trade = PaperTrade(data)
                        self._trades[trade.id] = trade
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("Skipping malformed trade line: %s", e)
            logger.info("Loaded %d paper trades from disk", len(self._trades))
        except Exception as e:
            logger.error("Failed to load paper trades: %s", e)

    def _save_trades(self) -> None:
        """Write all trades to JSONL (atomic write via temp file)."""
        tmp = self._trades_file.with_suffix(".tmp")
        try:
            with open(tmp, "w") as f:
                for trade in self._trades.values():
                    f.write(json.dumps(trade.to_dict()) + "\n")
            tmp.replace(self._trades_file)
        except Exception as e:
            logger.error("Failed to save paper trades: %s", e)
            if tmp.exists():
                tmp.unlink()

    # ── Trade Lifecycle ───────────────────────────────────────────

    def create_trade(self, data: Dict[str, Any]) -> PaperTrade:
        """
        Create a new paper trade.

        REQUIRED fields: symbol, entry_price, stop_loss, target_1
        OPTIONAL: direction, asset_type, strategy, quantity, confidence,
                  notes, target_2, target_3, trailing_stop_pct, max_hold_days,
                  scanner_data, tags, option_type, strike_price, expiration
        """
        # Validate required fields
        required = ["symbol", "entry_price", "stop_loss", "target_1"]
        missing = [f for f in required if f not in data or data[f] is None]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        # Validate entry/stop/target relationship
        entry = float(data["entry_price"])
        stop = float(data["stop_loss"])
        target = float(data["target_1"])
        direction = data.get("direction", "long")

        if direction == "long":
            if stop >= entry:
                raise ValueError("Stop loss must be below entry price for long trades")
            if target <= entry:
                raise ValueError("Target must be above entry price for long trades")
        else:
            if stop <= entry:
                raise ValueError("Stop loss must be above entry price for short trades")
            if target >= entry:
                raise ValueError("Target must be below entry price for short trades")

        # Calculate R:R and reject if too low
        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = reward / risk if risk > 0 else 0
        if rr < 1.0:
            raise ValueError(
                f"Risk:Reward ratio {rr:.2f} is below minimum 1.0. Adjust stop or target."
            )

        # Auto-calculate position size if not provided
        if "quantity" not in data or not data["quantity"]:
            max_risk_dollars = self._account_balance * (DEFAULT_MAX_RISK_PCT / 100)
            data["quantity"] = int(max_risk_dollars / risk) if risk > 0 else 0

        # Calculate position risk as % of account
        qty = float(data.get("quantity", 0))
        data["position_risk_pct"] = round((risk * qty / self._account_balance) * 100, 2)

        trade = PaperTrade(data)
        self._trades[trade.id] = trade
        self._save_trades()

        logger.info(
            "Paper trade created: %s %s %s @ %.2f | Stop: %.2f | Target: %.2f | R:R 1:%.1f | Qty: %.0f",  # noqa: E501
            trade.direction.upper(),
            trade.symbol,
            trade.asset_type,
            trade.entry_price,
            trade.stop_loss,
            trade.target_1,
            trade.risk_reward_ratio,
            trade.quantity,
        )
        return trade

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        reason: str = "manual",
        grade: str = "",
        notes: str = "",
    ) -> Optional[PaperTrade]:
        """Close an open trade."""
        trade = self._trades.get(trade_id)
        if not trade:
            return None
        if trade.status != "open":
            raise ValueError(f"Trade {trade_id} is already closed ({trade.status})")

        # Apply slippage based on asset type
        slippage = {
            "stock": DEFAULT_SLIPPAGE_STOCK,
            "option": DEFAULT_SLIPPAGE_OPTION,
            "crypto": DEFAULT_SLIPPAGE_CRYPTO,
        }.get(trade.asset_type, DEFAULT_SLIPPAGE_STOCK)

        trade.close(exit_price, reason, slippage)
        if grade:
            trade.trade_grade = grade
        if notes:
            trade.notes = (trade.notes + "\n" + notes).strip()

        self._save_trades()

        logger.info(
            "Paper trade closed: %s %s | P&L: $%.2f (%.1f%%) | R: %.2fR | Reason: %s",
            trade.symbol,
            trade.direction,
            trade.realized_pl,
            trade.realized_pl_pct,
            trade.r_multiple,
            reason,
        )
        return trade

    def update_prices(self, prices: Dict[str, float]) -> List[Dict[str, Any]]:
        """
        Update prices for all open trades. Returns list of triggered events.

        Args:
            prices: {symbol: current_price} mapping
        """
        triggers = []
        for trade in self._trades.values():
            if trade.status != "open":
                continue
            price = prices.get(trade.symbol)
            if price is None:
                continue

            trigger = trade.update_price(price)
            if trigger:
                triggers.append(
                    {
                        "trade_id": trade.id,
                        "symbol": trade.symbol,
                        "trigger": trigger,
                        "price": price,
                        "r_multiple": trade.r_multiple,
                        "pl": round(trade.unrealized_pl, 2),
                    }
                )

        if triggers or prices:
            self._save_trades()

        return triggers

    def delete_trade(self, trade_id: str) -> bool:
        """
        Delete a paper trade. Only open trades can be deleted.

        Raises KeyError if trade not found, ValueError if trade is closed.
        Returns True on successful deletion.
        """
        trade = self._trades.get(trade_id)
        if trade is None:
            raise KeyError(f"Trade {trade_id} not found")
        if trade.status != "open":
            raise ValueError(f"Cannot delete closed trade {trade_id} (status: {trade.status})")
        del self._trades[trade_id]
        self._save_trades()
        logger.info("Paper trade deleted: %s %s", trade.symbol, trade_id)
        return True

    def update_trade(self, trade_id: str, updates: Dict[str, Any]) -> Optional[PaperTrade]:
        """Update trade metadata (notes, grade, confidence, tags)."""
        trade = self._trades.get(trade_id)
        if not trade:
            return None

        if trade.status != "open":
            return None

        allowed = {
            "notes",
            "confidence",
            "trade_grade",
            "rules_followed",
            "tags",
            "trailing_stop_pct",
            "max_hold_days",
            "stop_loss",
            "target_1",
            "target_2",
            "target_3",
        }
        for key, value in updates.items():
            if key in allowed:
                setattr(trade, key, value)

        # Recalculate risk metrics if stop or target changed
        if "stop_loss" in updates or "target_1" in updates:
            trade.risk_per_share = abs(trade.entry_price - trade.stop_loss)
            trade.risk_reward_ratio = trade._calc_rr()
            trade.position_risk_dollars = trade.risk_per_share * abs(trade.quantity)

        self._save_trades()
        return trade

    # ── Queries ───────────────────────────────────────────────────

    def get_trade(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Get full trade details including price history."""
        trade = self._trades.get(trade_id)
        return trade.to_dict() if trade else None

    def get_trades(
        self, status: str = "all", strategy: str = "all", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List trades with optional filters."""
        trades = list(self._trades.values())

        if status != "all":
            if status == "open":
                trades = [t for t in trades if t.status == "open"]
            elif status == "closed":
                trades = [t for t in trades if t.status != "open"]
            else:
                trades = [t for t in trades if t.status == status]

        if strategy != "all":
            trades = [t for t in trades if t.strategy.lower() == strategy.lower()]

        # Sort: open trades first (by entry date desc), then closed (by exit date desc)
        open_trades = [t for t in trades if t.status == "open"]
        closed_trades = [t for t in trades if t.status != "open"]
        open_trades.sort(key=lambda t: t.entry_date, reverse=True)
        closed_trades.sort(key=lambda t: t.exit_date or t.entry_date, reverse=True)

        combined = open_trades + closed_trades
        return [t.to_summary() for t in combined[:limit]]

    def get_open_symbols(self) -> List[str]:
        """Get list of symbols with open trades (for price updates)."""
        return list({t.symbol for t in self._trades.values() if t.status == "open"})

    # ── Statistics ────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Calculate comprehensive trading statistics."""
        all_trades = list(self._trades.values())
        open_trades = [t for t in all_trades if t.status == "open"]
        closed_trades = [t for t in all_trades if t.status != "open"]

        winners = [t for t in closed_trades if t.realized_pl > 0]
        losers = [t for t in closed_trades if t.realized_pl < 0]
        breakeven = [t for t in closed_trades if t.realized_pl == 0]

        total_closed = len(closed_trades)
        win_rate = (len(winners) / total_closed * 100) if total_closed else 0

        avg_win = (sum(t.realized_pl for t in winners) / len(winners)) if winners else 0
        avg_loss = (sum(t.realized_pl for t in losers) / len(losers)) if losers else 0
        avg_win_r = (sum(t.r_multiple for t in winners) / len(winners)) if winners else 0
        avg_loss_r = (sum(t.r_multiple for t in losers) / len(losers)) if losers else 0

        gross_profit = sum(t.realized_pl for t in winners)
        gross_loss = abs(sum(t.realized_pl for t in losers))
        profit_factor = (
            (gross_profit / gross_loss)
            if gross_loss > 0
            else float("inf")
            if gross_profit > 0
            else 0
        )

        # Expectancy (avg $ per trade)
        expectancy = (
            (sum(t.realized_pl for t in closed_trades) / total_closed) if total_closed else 0
        )
        # Expectancy in R
        expectancy_r = (
            (sum(t.r_multiple for t in closed_trades) / total_closed) if total_closed else 0
        )

        # Current open P&L
        open_pl = sum(t.unrealized_pl for t in open_trades)

        # Total realized
        total_realized = sum(t.realized_pl for t in closed_trades)

        # By strategy breakdown
        strategies = {}
        for strat in {"GOAT", "BRAVO", "manual"}:
            strat_trades = [t for t in closed_trades if t.strategy.upper() == strat.upper()]
            strat_winners = [t for t in strat_trades if t.realized_pl > 0]
            strat_count = len(strat_trades)
            strategies[strat.lower()] = {
                "total_trades": strat_count,
                "win_rate": (len(strat_winners) / strat_count * 100) if strat_count else 0,
                "total_pl": round(sum(t.realized_pl for t in strat_trades), 2),
                "avg_r": round(sum(t.r_multiple for t in strat_trades) / strat_count, 2)
                if strat_count
                else 0,
            }

        # Equity curve (cumulative P&L over closed trades by exit date)
        equity_curve = []
        sorted_closed = sorted(closed_trades, key=lambda t: t.exit_date or "")
        running_pl = 0
        for t in sorted_closed:
            running_pl += t.realized_pl
            equity_curve.append(
                {
                    "date": (t.exit_date or t.entry_date)[:10],
                    "cumulative_pl": round(running_pl, 2),
                    "trade_id": t.id,
                    "symbol": t.symbol,
                    "r_multiple": t.r_multiple,
                }
            )

        # Streak tracking
        current_streak = 0
        streak_type = ""
        for t in reversed(sorted_closed):
            if t.realized_pl > 0:
                if streak_type == "" or streak_type == "win":
                    streak_type = "win"
                    current_streak += 1
                else:
                    break
            elif t.realized_pl < 0:
                if streak_type == "" or streak_type == "loss":
                    streak_type = "loss"
                    current_streak += 1
                else:
                    break

        # Graduation readiness check
        # Need: 30+ trades, 45%+ win rate, profit factor > 1.5, 90%+ rules followed
        rules_followed_pct = (
            (sum(1 for t in closed_trades if t.rules_followed) / total_closed * 100)
            if total_closed
            else 0
        )

        graduation = {
            "trades_needed": max(0, 30 - total_closed),
            "win_rate_ok": win_rate >= 45,
            "profit_factor_ok": profit_factor >= 1.5,
            "rules_ok": rules_followed_pct >= 90,
            "ready": (
                total_closed >= 30
                and win_rate >= 45
                and profit_factor >= 1.5
                and rules_followed_pct >= 90
            ),
        }

        return {
            "account_balance": self._account_balance,
            "total_trades": len(all_trades),
            "open_trades": len(open_trades),
            "closed_trades": total_closed,
            "winners": len(winners),
            "losers": len(losers),
            "breakeven": len(breakeven),
            "win_rate": round(win_rate, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_win_r": round(avg_win_r, 2),
            "avg_loss_r": round(avg_loss_r, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(expectancy, 2),
            "expectancy_r": round(expectancy_r, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "total_realized_pl": round(total_realized, 2),
            "open_unrealized_pl": round(open_pl, 2),
            "current_streak": current_streak,
            "streak_type": streak_type,
            "rules_followed_pct": round(rules_followed_pct, 1),
            "by_strategy": strategies,
            "equity_curve": equity_curve[-200:],  # Last 200 data points
            "graduation": graduation,
        }
