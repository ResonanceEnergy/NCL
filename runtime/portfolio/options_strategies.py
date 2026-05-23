"""
Static options-strategy definitions + a tiny matcher/suggester used by the
Portfolio OPTIONS sub-tab.

Three strategies are surfaced today:

  * 0DTE  — same-day-expiry index credit spreads / iron condors.
  * 5-Day Swing  — weekly debit/credit verticals held 3-5 trading days.
  * Long Call  — single-leg directional bet, 30-90 DTE or LEAP.

Everything in here is **static data + pure functions** — no LLM calls,
no network. The iOS layer renders the strategy cards verbatim and pipes
held positions / scanner hits through the matcher functions to attach a
strategy label per row.

The matcher uses a heuristic OCC-style symbol parse plus a couple of
liquidity / IV / direction filters. It is intentionally conservative —
"Other" is the right answer when the position doesn't cleanly fit one
of the three named playbooks.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Strategy definition
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategyDefinition:
    """Static description of one options strategy."""

    key: str                       # "0DTE" | "5DAY" | "LONGCALL"
    name: str                      # "0DTE Index Credit"
    tagline: str                   # one-line subtitle
    description: str               # 2-3 sentence overview
    best_market_conditions: list[str]
    entry_triggers: list[str]
    exit_rules: list[str]
    sizing_rule: str
    greeks_profile: dict[str, str]   # {"delta": "...", "theta": "...", ...}
    typical_dte_range: tuple[int, int]  # (min_dte, max_dte) inclusive
    common_pitfalls: list[str]
    practitioners: list[str]
    color_hex: str = "#AF52DE"     # for iOS badge tint

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # tuples become lists in JSON — keep them ordered + named.
        d["typical_dte_range"] = {
            "min": self.typical_dte_range[0],
            "max": self.typical_dte_range[1],
        }
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Strategy library
# ─────────────────────────────────────────────────────────────────────────────


ZERO_DTE = StrategyDefinition(
    key="0DTE",
    name="0DTE Index Credit",
    tagline="Same-day expiry credit spreads / iron condors on SPX / SPY / QQQ",
    description=(
        "Sell defined-risk credit structures that expire by 4pm ET the same "
        "session. Wins by harvesting accelerated theta inside the final "
        "trading day; loses when an intraday range breakout pushes price "
        "through a short strike. Cash-settled SPX is preferred — no overnight "
        "assignment risk, no early-exercise risk on the call side."
    ),
    best_market_conditions=[
        "IV rank 20-60 (enough premium, not panic-driven)",
        "Range-bound regime: VIX 12-22 and a flat overnight session",
        "No Fed / CPI / NFP print before close",
        "Avoid first 30 minutes (opening auction chop) and last 15 (gamma cliff)",
    ],
    entry_triggers=[
        "After 10:00 AM ET once the opening range is set",
        "Short strikes at 0.10-0.15 delta on each side (~0.5-0.8 expected move)",
        "Equal credit on both wings of the iron condor",
        "At least 30 minutes between adds; max ~5 entries per session",
    ],
    exit_rules=[
        "Profit target: close at 50-75% of credit received (don't wait for expiry)",
        "Stop: roll or close if a short strike is touched OR loss hits 2x credit",
        "Time stop: flat by 3:45 PM ET — gamma risk in the last 15 min is brutal",
        "Never carry overnight — they expire worthless or in-the-money by 4pm",
    ],
    sizing_rule=(
        "Max 1-2% of account risk per trade (defined risk = wing width - credit). "
        "Skip the trade if a 5-point spread would be more than 1% of NLV."
    ),
    greeks_profile={
        "delta": "near-zero net (condor) or small directional (-0.10 to +0.10)",
        "gamma": "very high negative — primary risk vector",
        "theta": "very high positive — the entire edge",
        "vega": "small negative (1-3% of credit per IV point)",
    },
    typical_dte_range=(0, 0),
    common_pitfalls=[
        "Sizing for the win rate, not the tail loss — 70% wins / 30% blowouts is a losing math if losses aren't capped",
        "Trading 0DTE on single-name equities (assignment + earnings risk)",
        "Adding to losers — pin risk is non-linear past the short strike",
        "Holding into the final 15 minutes when gamma is at its peak",
    ],
    practitioners=[
        "tastytrade research team (Sosnoff, Battista)",
        "SpotGamma (dealer-flow context for 0DTE)",
        "Theta Profits (9k+ trade journal on 0DTE breakeven condor)",
    ],
    color_hex="#FF3B30",   # red — high-octane / fast clock
)


FIVE_DAY_SWING = StrategyDefinition(
    key="5DAY",
    name="5-Day Swing",
    tagline="Weekly debit / credit vertical spreads held 3-5 trading days",
    description=(
        "Capture a multi-day directional move with a defined-risk vertical. "
        "Sized to survive an overnight gap; closed when either the target "
        "level prints, the technical thesis breaks, or the time stop fires "
        "to dodge end-of-week theta decay."
    ),
    best_market_conditions=[
        "Sector rotation or a clean breakout setup with 2x+ ATR room to target",
        "Post-earnings IV crush (volatility cratered — debit spreads cheap)",
        "IV rank 30-50 — high enough to sell, low enough not to torch the long leg",
        "Trending tape — avoid in chop (whipsaws kill the time stop)",
    ],
    entry_triggers=[
        "Break + retest of a multi-day pivot / 20 EMA with momentum confirmation",
        "Unusual call flow > $250k premium when going long (or put flow when short)",
        "Choose strikes 3-5 weeks out so you have rolldown room, NOT same-week",
        "ATM or one-strike ITM long leg; short leg one strike further from price",
    ],
    exit_rules=[
        "Profit target: close at 50% of max profit (debit) or 80% of max credit",
        "Stop: 50% of premium paid (debit) or hard stop at 2x credit received",
        "Time stop: flat by Friday morning — never hold a weekly into the final session",
        "Thesis break: if the underlying closes back through your entry pivot, exit immediately",
    ],
    sizing_rule=(
        "Risk 1-2% of account per spread. Position size = (account * 0.015) / "
        "(spread width - credit). Never have more than 5 open swing spreads."
    ),
    greeks_profile={
        "delta": "+0.30 to +0.50 (long debit) or -0.20 to -0.35 (short credit)",
        "gamma": "moderate — payoff curves up into the short strike",
        "theta": "negative for debit / positive for credit (~$5-15 per day per spread)",
        "vega": "small positive (debit) or small negative (credit), ~10% of premium per IV point",
    },
    typical_dte_range=(7, 21),
    common_pitfalls=[
        "Buying weekly options (≤7 DTE) and calling it a swing — that's gambling, not swinging",
        "Skipping the time stop and watching theta eat the premium over the weekend",
        "Stacking 5 spreads on the same sector — that's one trade, not five",
        "Letting a winner round-trip past the 50% profit target waiting for max",
    ],
    practitioners=[
        "Tom Sosnoff (tastytrade swing playbook)",
        "Sky View Trading (vertical spread mechanics)",
        "Damocles (credit-spread exit rule frameworks)",
    ],
    color_hex="#FF7300",   # orange — medium tempo
)


LONG_CALL = StrategyDefinition(
    key="LONGCALL",
    name="Long Call",
    tagline="Single-leg directional call — 30-90 DTE or LEAP for capital efficiency",
    description=(
        "Buy a single call to express a high-conviction bullish view with "
        "defined max loss = premium paid. Used as a stock replacement (deep "
        "ITM, high delta) or as leveraged exposure (ATM, 60-90 DTE) when "
        "the move is expected to play out over weeks rather than days."
    ),
    best_market_conditions=[
        "IV rank < 40 — buying premium when implied vol is rich is a tax",
        "Clean uptrend on the daily / weekly chart (price > 50 SMA > 200 SMA)",
        "Catalyst within the holding window (earnings, product launch, FDA, etc.) — but BEFORE the IV ramp",
        "Avoid the week of earnings — IV crush will hurt even if direction is right",
    ],
    entry_triggers=[
        "Breakout above a multi-month base with confirming volume",
        "Bullish unusual call flow accumulating in 30-90 DTE strikes",
        "Strike selection: 0.70-0.80 delta ITM (stock replacement) OR 0.40-0.55 delta ATM (leverage)",
        "Expiry: minimum 45 DTE to keep theta tolerable; 60-90 DTE is the sweet spot",
    ],
    exit_rules=[
        "Profit target: 50-100% of premium paid — most long calls round-trip if held to expiry",
        "Stop: -50% of premium OR underlying closes below the breakout level",
        "Time stop: roll or close at 21 DTE to dodge the gamma/theta acceleration zone",
        "Never let a long call expire — close it 1 DTE at the latest",
    ],
    sizing_rule=(
        "Position size = (account * 0.02) / call premium per contract * 100. "
        "Each contract is full premium at risk — sizing by share-equivalent is "
        "the most common rookie mistake."
    ),
    greeks_profile={
        "delta": "+0.40 to +0.80 depending on strike (ATM ~0.50, deep ITM ~0.80)",
        "gamma": "positive, peaks at ATM — accelerates the delta as price moves up",
        "theta": "negative — bleeds ~1-3% of premium per day, worst inside 30 DTE",
        "vega": "positive — wins on an IV expansion, loses on a crush even if direction is right",
    },
    typical_dte_range=(30, 365),
    common_pitfalls=[
        "Buying OTM lottery tickets and waiting — most expire worthless",
        "Buying calls into earnings IV ramp — pays the vol premium then gets crushed",
        "Sizing by 'shares-controlled' instead of premium-at-risk",
        "Holding through 21 DTE — theta acceleration eats the position alive",
    ],
    practitioners=[
        "Options Alpha (Kirk Du Plessis) — strike-selection framework",
        "projectfinance (Chris Butler) — long-call mechanics + Greeks walkthrough",
        "tastytrade — when NOT to buy calls (IVR > 50 caveat)",
    ],
    color_hex="#30D158",   # green — bullish / patient
)


STRATEGIES: tuple[StrategyDefinition, ...] = (ZERO_DTE, FIVE_DAY_SWING, LONG_CALL)
STRATEGY_BY_KEY: dict[str, StrategyDefinition] = {s.key: s for s in STRATEGIES}


# ─────────────────────────────────────────────────────────────────────────────
# OCC symbol parsing
# ─────────────────────────────────────────────────────────────────────────────

# Two common encodings we see across our adapters:
#   IBKR / OCC style:   "AAPL  240621C00185000"  (6-char root, space-pad)
#   Compact style:      "SLV270115C65000"        (root + YYMMDD + C/P + strike*1000)
#
# We accept both. Strike is reported as integer dollars in the OCC standard
# (multiplied by 1000). Expiry is YYMMDD.

_COMPACT_OPTION_RE = re.compile(
    r"^(?P<root>[A-Z]{1,6})(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{1,8})$"
)
_OCC_OPTION_RE = re.compile(
    r"^(?P<root>[A-Z.]{1,6})\s*(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{1,8})$"
)


def parse_option_symbol(symbol: str) -> Optional[dict[str, Any]]:
    """
    Parse an OCC-style option symbol into root/expiry/right/strike.

    Returns ``None`` for plain equity tickers — callers use that to gate
    option-only logic.
    """
    if not symbol:
        return None
    s = symbol.strip().upper()
    m = _COMPACT_OPTION_RE.match(s) or _OCC_OPTION_RE.match(s.replace(" ", ""))
    if not m:
        return None
    yy, mm, dd = int(m.group("yy")), int(m.group("mm")), int(m.group("dd"))
    # 2-digit years: 00-79 → 20yy, 80-99 → 19yy (OCC convention)
    year = 2000 + yy if yy < 80 else 1900 + yy
    try:
        expiry = datetime(year, mm, dd, tzinfo=timezone.utc).date()
    except ValueError:
        return None
    strike_raw = int(m.group("strike"))
    strike = strike_raw / 1000.0 if strike_raw >= 1000 else float(strike_raw)
    right = m.group("cp")
    return {
        "underlying": m.group("root"),
        "expiry": expiry.isoformat(),
        "right": right,
        "strike": strike,
        "is_call": right == "C",
        "is_put": right == "P",
    }


def days_to_expiry(expiry_iso: str, now: Optional[datetime] = None) -> Optional[int]:
    """Whole-day distance to expiry. Negative means already expired."""
    try:
        exp = datetime.fromisoformat(expiry_iso).date()
    except (TypeError, ValueError):
        return None
    today = (now or datetime.now(timezone.utc)).date()
    return (exp - today).days


# ─────────────────────────────────────────────────────────────────────────────
# Strategy matcher
# ─────────────────────────────────────────────────────────────────────────────


def match_strategy(position: dict[str, Any]) -> str:
    """
    Classify a held option position into one of the named strategies, or
    ``"Other"`` if it doesn't cleanly fit any.

    Heuristic — we only look at structural features (DTE + right + qty sign)
    plus underlying class. We deliberately do **not** look at delta /
    implied vol here; adapters don't reliably populate Greeks today and the
    matcher needs to work with what we have.
    """
    if not position:
        return "Other"
    if (position.get("asset_class") or "").lower() != "option":
        return "Other"

    symbol = position.get("symbol") or ""
    parsed = parse_option_symbol(symbol)
    if not parsed:
        # Some adapters store the underlying in `symbol` and put the
        # contract metadata in `name`. Try the metadata path next.
        meta = position.get("metadata") or {}
        if meta.get("expiry") and meta.get("strike") and meta.get("right"):
            parsed = {
                "underlying": position.get("underlying") or symbol,
                "expiry": meta["expiry"],
                "right": meta["right"],
                "strike": float(meta["strike"]),
                "is_call": meta["right"] == "C",
                "is_put": meta["right"] == "P",
            }
        else:
            return "Other"

    dte = days_to_expiry(parsed["expiry"])
    if dte is None:
        return "Other"

    qty = float(position.get("quantity") or 0)
    is_long = qty > 0
    underlying = (parsed["underlying"] or "").upper()
    index_like = underlying in {"SPX", "SPXW", "XSP", "SPY", "QQQ", "IWM", "NDX", "RUT"}

    # 0DTE: same-day expiry, index-class underlying
    if dte <= 0 and index_like:
        return "0DTE"

    # 5-Day Swing: vertical-spread DTE window, either direction
    if 1 <= dte <= 21:
        return "5DAY"

    # Long Call: long call with 30+ DTE
    if is_long and parsed["is_call"] and dte >= 30:
        return "LONGCALL"

    return "Other"


def enrich_position_with_strategy(position: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-copied position dict with strategy fields attached."""
    out = dict(position)
    matched = match_strategy(position)
    out["matched_strategy"] = matched
    out["matched_strategy_name"] = (
        STRATEGY_BY_KEY[matched].name if matched in STRATEGY_BY_KEY else "Other"
    )

    parsed = parse_option_symbol(out.get("symbol") or "")
    if parsed:
        out["option_underlying"] = parsed["underlying"]
        out["option_expiry"] = parsed["expiry"]
        out["option_right"] = parsed["right"]
        out["option_strike"] = parsed["strike"]
        dte = days_to_expiry(parsed["expiry"])
        if dte is not None:
            out["option_dte"] = dte
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Suggestion engine — pure filters on scanner hits / unusual flow rows
# ─────────────────────────────────────────────────────────────────────────────


def suggest_entries(
    scanner_hits: Iterable[dict[str, Any]],
    strategy_name: str,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """
    Filter a heterogeneous list of scanner hits / options-flow rows down to
    those that fit the requested strategy's profile.

    Inputs accept three shapes (the union of what our scanners produce):
      * GOAT scanner row    — {"symbol", "score", "trend", ...}
      * Bravo swing row     — {"symbol", "setup", "atr", "rr", ...}
      * Options-flow row    — {"ticker", "call_premium", "put_premium",
                              "call_put_ratio", "trade_count", ...}

    Output is the same dict-shape with a small ``_match_reason`` field
    appended so the iOS layer can render "why this matched".
    """
    key = (strategy_name or "").upper()
    if key not in STRATEGY_BY_KEY:
        return []

    results: list[dict[str, Any]] = []
    for hit in scanner_hits:
        if not isinstance(hit, dict):
            continue

        ticker = (hit.get("ticker") or hit.get("symbol") or "").upper()
        if not ticker:
            continue

        match_reason: Optional[str] = None

        if key == "0DTE":
            # Only index-class underliers are appropriate for 0DTE.
            if ticker not in {"SPX", "SPXW", "XSP", "SPY", "QQQ", "IWM", "NDX", "RUT"}:
                continue
            # Prefer balanced flow (range-bound implication) — C/P ratio near 1
            ratio = float(hit.get("call_put_ratio") or 0)
            if 0.0 < ratio:
                if 0.6 <= ratio <= 1.7:
                    match_reason = f"Balanced flow on {ticker} (C/P {ratio:.2f})"
                else:
                    # Skewed flow → directional bias incompatible with iron condor
                    continue
            else:
                # GOAT/Bravo hit on an index without flow context → still useful
                match_reason = f"Index-class underlying suitable for 0DTE"

        elif key == "5DAY":
            # Vertical-spread candidates: liquid flow OR a fresh GOAT/Bravo setup
            premium = float(hit.get("total_premium_usd") or 0)
            ratio = float(hit.get("call_put_ratio") or 0)
            setup = (hit.get("setup") or hit.get("trend") or "").lower()
            if premium >= 250_000 and ratio > 0:
                bias = "bullish" if ratio >= 1.5 else "bearish" if ratio <= 0.6 else "neutral"
                if bias == "neutral":
                    continue
                match_reason = (
                    f"${premium/1000:.0f}k flow, {bias} bias — vertical spread fits"
                )
            elif setup in {"breakout", "trend", "momentum", "swing"}:
                match_reason = f"Scanner '{setup}' setup, 7-21 DTE vertical-spread window"
            else:
                continue

        elif key == "LONGCALL":
            # Bullish, high-conviction directional bets
            premium = float(hit.get("total_premium_usd") or 0)
            call_prem = float(hit.get("call_premium") or 0)
            put_prem = float(hit.get("put_premium") or 0)
            ratio = (call_prem / put_prem) if put_prem else (call_prem / 1.0 if call_prem else 0.0)

            if premium >= 500_000 and ratio >= 2.0:
                match_reason = (
                    f"${premium/1000:.0f}k call-heavy flow (C/P {ratio:.2f}) — bullish conviction"
                )
            elif (hit.get("trend") or "").lower() in {"uptrend", "bullish"}:
                match_reason = "Scanner flagged underlying in confirmed uptrend"
            else:
                continue

        if match_reason is None:
            continue

        row = dict(hit)
        row["_strategy"] = key
        row["_match_reason"] = match_reason
        row["_ticker"] = ticker
        results.append(row)
        if len(results) >= max_results:
            break

    return results


# ─────────────────────────────────────────────────────────────────────────────
# JSON helpers for the FastAPI route
# ─────────────────────────────────────────────────────────────────────────────


def all_strategies_payload() -> list[dict[str, Any]]:
    """Stable JSON payload for ``GET /portfolio/options/strategies``."""
    return [s.to_dict() for s in STRATEGIES]
