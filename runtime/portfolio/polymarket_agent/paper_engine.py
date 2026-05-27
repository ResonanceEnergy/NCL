"""
Polymarket paper-bet engine — Wave 14R R4

Separate from the equity PaperTradingEngine because prediction markets
have binary 0/1 outcomes with hard resolution deadlines instead of
continuous prices with stops/targets/trailing-stops.

Each bet:
  entry_price = market_yes_price at open
  side        = "YES" | "NO"
  stake_usd   = dollar amount risked
  shares      = stake_usd / entry_price (for YES) or stake_usd / (1-entry_price) (for NO)

Resolution:
  YES bet wins  → payout = shares * $1.00       → P&L = stake * (1/entry - 1)
  YES bet loses → payout = shares * $0.00       → P&L = -stake
  NO  bet wins  → payout = shares * $1.00       → P&L = stake * (1/(1-entry) - 1)
  NO  bet loses → payout = shares * $0.00       → P&L = -stake

Half-loss thesis-break exit:
  Operator-configurable; default OFF. If enabled, closes at -50% if
  market price moves against us by >X% before resolution.

Storage:
  data/portfolio/polymarket_agent/bets.jsonl   (append-only log)
  data/portfolio/polymarket_agent/open_bets.json (live snapshot)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.polymarket_agent.paper_engine")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "polymarket_agent"
BETS_LOG = DATA_DIR / "bets.jsonl"
OPEN_SNAPSHOT = DATA_DIR / "open_bets.json"


@dataclass
class PolymarketPaperBet:
    bet_id: str
    market_slug: str
    market_question: str
    side: str                          # "YES" | "NO"
    entry_price: float                 # 0-1 yes_price at open
    stake_usd: float                   # cash committed
    shares: float                      # entry_price * shares = stake
    entry_at_iso: str
    end_date_iso: Optional[str] = None
    edge_pp_at_entry: Optional[float] = None
    prediction_id: Optional[str] = None
    prediction_title: Optional[str] = None
    edge_terms: list[str] = field(default_factory=list)
    status: str = "open"                # open | resolved_win | resolved_loss | closed_manual
    exit_price: Optional[float] = None  # 0-1 final price (or 0/1 on resolution)
    exit_at_iso: Optional[str] = None
    realized_pl_usd: Optional[float] = None
    realized_r_multiple: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class PolymarketPaperEngine:
    _instance: Optional["PolymarketPaperEngine"] = None

    def __init__(self) -> None:
        self._bets: dict[str, PolymarketPaperBet] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    @classmethod
    def get(cls) -> "PolymarketPaperEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_dir(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _load_from_disk(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if OPEN_SNAPSHOT.exists():
            try:
                raw = json.loads(OPEN_SNAPSHOT.read_text())
                for d in raw.get("open_bets", []):
                    bet = PolymarketPaperBet(**{
                        k: v for k, v in d.items()
                        if k in PolymarketPaperBet.__dataclass_fields__
                    })
                    if bet.status == "open":
                        self._bets[bet.bet_id] = bet
                log.info("[POLY-PAPER] loaded %d open bets", len(self._bets))
            except Exception as e:
                log.warning("[POLY-PAPER] snapshot load failed: %s", e)

    def _persist_snapshot_unlocked(self) -> None:
        self._ensure_dir()
        open_list = [b.to_dict() for b in self._bets.values() if b.status == "open"]
        payload = {
            "snapshot_at_iso": datetime.now(timezone.utc).isoformat(),
            "open_bet_count": len(open_list),
            "open_bets": open_list,
        }
        try:
            tmp = OPEN_SNAPSHOT.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2, default=str))
            tmp.replace(OPEN_SNAPSHOT)
        except Exception as e:
            log.error("[POLY-PAPER] snapshot write failed: %s", e)

    def _append_log_unlocked(self, bet: PolymarketPaperBet) -> None:
        self._ensure_dir()
        try:
            with BETS_LOG.open("a") as f:
                f.write(json.dumps(bet.to_dict(), default=str) + "\n")
        except Exception as e:
            log.error("[POLY-PAPER] log append failed: %s", e)

    async def open_bet(
        self,
        *,
        market_slug: str,
        market_question: str,
        side: str,
        entry_price: float,
        stake_usd: float,
        end_date_iso: Optional[str] = None,
        edge_pp_at_entry: Optional[float] = None,
        prediction_id: Optional[str] = None,
        prediction_title: Optional[str] = None,
        edge_terms: Optional[list[str]] = None,
        notes: str = "",
    ) -> PolymarketPaperBet:
        side = side.upper().strip()
        if side not in ("YES", "NO"):
            raise ValueError(f"side must be YES or NO, got {side!r}")
        if not (0 < entry_price < 1):
            raise ValueError(f"entry_price must be in (0, 1), got {entry_price}")
        if stake_usd <= 0:
            raise ValueError(f"stake_usd must be positive, got {stake_usd}")

        # Cost basis depends on side: YES pays at entry_price, NO at 1-entry_price
        cost_per_share = entry_price if side == "YES" else (1.0 - entry_price)
        shares = round(stake_usd / cost_per_share, 4) if cost_per_share > 0 else 0
        bet = PolymarketPaperBet(
            bet_id=uuid.uuid4().hex[:12],
            market_slug=market_slug,
            market_question=market_question,
            side=side,
            entry_price=round(entry_price, 4),
            stake_usd=round(stake_usd, 2),
            shares=shares,
            entry_at_iso=datetime.now(timezone.utc).isoformat(),
            end_date_iso=end_date_iso,
            edge_pp_at_entry=edge_pp_at_entry,
            prediction_id=prediction_id,
            prediction_title=prediction_title,
            edge_terms=edge_terms or [],
            notes=notes,
        )
        async with self._lock:
            self._load_from_disk()
            self._bets[bet.bet_id] = bet
            self._append_log_unlocked(bet)
            self._persist_snapshot_unlocked()
        log.info(
            "[POLY-PAPER] OPEN %s %s @ $%.2f stake=$%.2f shares=%.2f (edge=%.1fpp)",
            bet.side, bet.market_slug[:40], bet.entry_price, bet.stake_usd,
            bet.shares, bet.edge_pp_at_entry or 0,
        )
        return bet

    async def resolve_bet(
        self,
        bet_id: str,
        *,
        outcome: str,        # "YES_WON" | "NO_WON" | "CANCELLED"
        notes: str = "",
    ) -> PolymarketPaperBet:
        async with self._lock:
            self._load_from_disk()
            bet = self._bets.get(bet_id)
            if bet is None:
                raise KeyError(f"bet {bet_id} not found")
            if bet.status != "open":
                raise ValueError(f"bet {bet_id} already {bet.status}")

            cost_per_share = bet.entry_price if bet.side == "YES" else (1.0 - bet.entry_price)
            if outcome == "CANCELLED":
                bet.status = "closed_manual"
                bet.exit_price = bet.entry_price
                bet.realized_pl_usd = 0.0
            else:
                we_won = (bet.side == "YES" and outcome == "YES_WON") or \
                         (bet.side == "NO" and outcome == "NO_WON")
                if we_won:
                    bet.status = "resolved_win"
                    bet.exit_price = 1.0
                    payout = bet.shares * 1.0
                    bet.realized_pl_usd = round(payout - bet.stake_usd, 2)
                else:
                    bet.status = "resolved_loss"
                    bet.exit_price = 0.0
                    bet.realized_pl_usd = round(-bet.stake_usd, 2)

            if cost_per_share > 0 and bet.stake_usd > 0:
                bet.realized_r_multiple = round(bet.realized_pl_usd / bet.stake_usd, 3)
            bet.exit_at_iso = datetime.now(timezone.utc).isoformat()
            if notes:
                bet.notes = (bet.notes + "\n" + notes).strip()

            self._append_log_unlocked(bet)
            self._persist_snapshot_unlocked()
        log.info(
            "[POLY-PAPER] RESOLVE %s %s: pl=$%+.2f r=%+.2fR (%s)",
            bet.side, bet.market_slug[:40], bet.realized_pl_usd or 0,
            bet.realized_r_multiple or 0, outcome,
        )
        return bet

    async def close_manual(self, bet_id: str, exit_price: float, notes: str = "") -> PolymarketPaperBet:
        """Close at current market price (early exit, half-loss handoff, etc)."""
        async with self._lock:
            self._load_from_disk()
            bet = self._bets.get(bet_id)
            if bet is None:
                raise KeyError(f"bet {bet_id} not found")
            if bet.status != "open":
                raise ValueError(f"bet {bet_id} already {bet.status}")

            if bet.side == "YES":
                # Selling shares at current price
                proceeds = bet.shares * exit_price
            else:  # NO
                # Selling NO shares = price went FROM 1-entry TO 1-exit
                proceeds = bet.shares * (1.0 - exit_price)
            bet.status = "closed_manual"
            bet.exit_price = round(exit_price, 4)
            bet.realized_pl_usd = round(proceeds - bet.stake_usd, 2)
            if bet.stake_usd > 0:
                bet.realized_r_multiple = round(bet.realized_pl_usd / bet.stake_usd, 3)
            bet.exit_at_iso = datetime.now(timezone.utc).isoformat()
            if notes:
                bet.notes = (bet.notes + "\n" + notes).strip()
            self._append_log_unlocked(bet)
            self._persist_snapshot_unlocked()
        log.info(
            "[POLY-PAPER] CLOSE %s %s @ $%.2f → pl=$%+.2f",
            bet.side, bet.market_slug[:40], exit_price, bet.realized_pl_usd or 0,
        )
        return bet

    def list_open(self) -> list[PolymarketPaperBet]:
        self._load_from_disk()
        return [b for b in self._bets.values() if b.status == "open"]

    def list_closed(self, limit: int = 50) -> list[dict]:
        """Read closed bets from the append-only log."""
        if not BETS_LOG.exists():
            return []
        out: list[dict] = []
        try:
            with BETS_LOG.open() as f:
                for ln in f:
                    try:
                        d = json.loads(ln)
                        if d.get("status") in ("resolved_win", "resolved_loss", "closed_manual"):
                            out.append(d)
                    except Exception:
                        continue
        except Exception:
            return []
        # Most recent last in file
        out.sort(key=lambda d: d.get("exit_at_iso") or "", reverse=True)
        return out[:limit]

    def stats(self) -> dict:
        closed = self.list_closed(limit=10_000)
        wins = sum(1 for d in closed if d.get("status") == "resolved_win")
        losses = sum(1 for d in closed if d.get("status") == "resolved_loss")
        manual = sum(1 for d in closed if d.get("status") == "closed_manual")
        total = wins + losses + manual
        pl_sum = sum(float(d.get("realized_pl_usd") or 0) for d in closed)
        r_sum = sum(float(d.get("realized_r_multiple") or 0) for d in closed)
        hit_rate = (wins / max(1, wins + losses)) if (wins + losses) else 0.0
        return {
            "total_closed": total,
            "wins": wins,
            "losses": losses,
            "closed_manual": manual,
            "hit_rate": round(hit_rate, 3),
            "total_realized_pl_usd": round(pl_sum, 2),
            "total_realized_R": round(r_sum, 2),
            "open_count": len(self.list_open()),
        }


def get_engine() -> PolymarketPaperEngine:
    return PolymarketPaperEngine.get()
