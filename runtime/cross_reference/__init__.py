"""Wave 14X-Y Phase 1B-3 (2026-05-29) — Cross-Reference Engine.

NATRIX's breakthrough: split AWAREBOT (intel/entertainment camp, loose
filtering) from TRADERAGENT (portfolio/serious camp, tight gates). The
piece that connects them is THIS module — promotes converging AWAREBOT
signals to PROMOTED_CANDIDATE status so the trader can evaluate them.

Promotion rules (any one fires):

  1. **Ticker convergence**: same ticker mentioned in ≥2 DISTINCT
     AWAREBOT sources within last 4h
  2. **Theme convergence**: shared keyword cluster across ≥3 distinct
     sources within last 24h
  3. **News+Trends double-verifier**: ticker hit in BOTH news (RSS) AND
     google_trends on same day — NATRIX's "if it's in the press AND
     spiking in search, that's confirmation"

Writes to `data/cross_reference/promotions.jsonl` (append, deduped by
(ticker, day) so we don't re-promote the same hot-converged ticker
hourly). Returns the newly-promoted candidates for the caller to push
into TRADERAGENT via `intel_request("awarebot.promoted_candidate", ...)`.

Pure pull-from-disk module — no LLM cost, no API calls. Fast enough to
run every 5 min from the scheduler.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.cross_reference")

NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
SIGNAL_LOG = NCL_BASE / "data" / "intelligence" / "agent_signals.jsonl"
PROMO_DIR = NCL_BASE / "data" / "cross_reference"
PROMO_LOG = PROMO_DIR / "promotions.jsonl"

# AWAREBOT-camp source prefixes (per INTEL_MANDATE.md + LANE_ARCHITECTURE).
# Anything NOT in this set is portfolio-side / decision-grade and doesn't
# count as a cross-reference vote.
_INTEL_SOURCES = {
    "reddit", "youtube",
    # Wave 14CR — dropped phantom "youtube_council" / "ytc". The YTC
    # rollup emits with source="youtube" — these two were never used
    # by anything and counted as one extra vote in convergence rules
    # against zero rows.
    "polymarket", "google_trends", "news",
    "x_twitter", "x", "twitter",
    "markets", "yfinance",  # ambient market context counts as 0.5 (see _is_intel_source)
}

# Ticker extraction: $TICKER notation OR bare uppercase 1-5 letters that
# pass a stoplist. Stoplist prevents common English words from matching.
_TICKER_RX = re.compile(r"(?:\$([A-Z]{1,5})|\b([A-Z]{2,5})\b)")
_TICKER_STOPLIST = {
    "THE", "AND", "FOR", "ARE", "WAS", "WERE", "BUT", "NOT", "YOU", "ALL",
    "HAS", "HAD", "HAVE", "HIS", "HER", "WHO", "WHAT", "WHEN", "WHY", "HOW",
    "GET", "GOT", "TWO", "ONE", "NEW", "OLD", "BIG", "TOP", "OFF", "OUT",
    "USA", "USD", "CEO", "CFO", "CTO", "COO", "API", "IPO", "ETF", "VIX",
    "GDP", "CPI", "FED", "ECB", "BOJ", "PBOC", "EOD", "ATH", "ATL", "YTD",
    "QTD", "MTD", "EPS", "PE", "ROI", "ROE", "EBIT", "EBITDA", "FOMC", "OPEX",
    "NCL",  # us!
    # Wave 14X-4c (2026-05-29): false-positive tickers seen in real promotions
    "US", "WE", "AM", "PM", "AI",  # overloaded common words
    "OK", "NO", "GO", "DO", "BE", "BY", "OR", "IF", "IT", "IS", "IN", "ON",
    "AS", "AT", "TO", "OF", "UP", "MY", "ME", "SO",
    "TLDR", "TLDR", "QNA", "FAQ", "AKA", "FYI", "ASAP", "ETA", "EU", "UK",
    "JP", "CN", "AR", "AF", "BR", "MX", "RU", "IR",  # countries with overlapping symbols
    "GMT", "EST", "PST", "UTC", "ET", "CT", "MT",
    "BTC", "ETH",  # too generic for trade-relevant ticker convergence (use specific pairs)
    "VS", "WP", "PR", "QA",
}

# Theme keywords for theme-convergence rule (rule 2). Each cluster is a
# rough topic — if signals from ≥3 distinct sources hit ANY keyword in the
# same cluster within 24h, the cluster gets promoted (not a ticker).
_THEME_CLUSTERS: dict[str, list[str]] = {
    "rate_policy":     ["fomc", "fed", "rate", "rates", "powell", "hawkish", "dovish"],
    "ai_capex":        ["ai capex", "ai infrastructure", "nvidia", "datacenter", "gpu demand"],
    "energy_supply":   ["opec", "crude", "oil supply", "barrel", "wti"],
    "crypto_macro":    ["bitcoin etf", "etf flows", "spot etf", "halving"],
    "geopolitical":    ["taiwan", "tariff", "sanction", "war", "ceasefire"],
}


@dataclass
class PromotedCandidate:
    """One promoted candidate — the entry written to promotions.jsonl."""

    promoted_at: str
    rule: str  # 'ticker_converge' | 'theme_converge' | 'news_trends_double'
    ticker: Optional[str] = None
    theme: Optional[str] = None  # for theme_converge only
    convergence_strength: int = 0  # number of distinct sources
    sources: list[str] = field(default_factory=list)
    signal_ids: list[str] = field(default_factory=list)
    sample_titles: list[str] = field(default_factory=list)
    window_hours: int = 4

    def dedup_key(self) -> str:
        """Same (ticker, day) only promotes once."""
        day = self.promoted_at[:10]
        if self.ticker:
            return f"ticker:{self.ticker}:{day}"
        if self.theme:
            return f"theme:{self.theme}:{day}"
        return f"unknown:{day}"


# ─────────────────────────────────────────────────────────────────────
# Signal reading
# ─────────────────────────────────────────────────────────────────────


def _is_intel_source(source: str) -> bool:
    """Is this source an AWAREBOT-camp source that votes in cross-ref?"""
    s = (source or "").lower()
    # Tail-match: "reddit:wallstreetbets" → "reddit"
    head = s.split(":")[0]
    return head in _INTEL_SOURCES


def _extract_tickers(text: str) -> set[str]:
    """Extract candidate tickers, filtered against the known-good universe.

    Wave 14CM (2026-05-31): bare-uppercase matches now must clear the
    ticker_universe whitelist. NATRIX trial-run flagged 35+ false
    positives (NOW / REST / THIS / FREE / OS / NEED / YOUR / WILL /
    GREAT / etc.) — stop-list alone can't catch them all. The $TICKER
    notation stays always-trusted; bare matches go through is_valid_ticker.
    """
    if not text:
        return set()
    try:
        from ..intelligence.ticker_universe import is_valid_ticker
    except Exception:
        # Universe unavailable — fall back to stop-list-only (legacy
        # behavior). Loud at debug so we notice in logs.
        is_valid_ticker = None
    found: set[str] = set()
    for m in _TICKER_RX.finditer(text):
        # group(1) = $TICKER (always trusted), group(2) = bare uppercase
        dollar_ticker = m.group(1)
        bare_ticker = m.group(2)
        ticker = dollar_ticker or bare_ticker
        if not ticker:
            continue
        ticker = ticker.upper()
        if ticker in _TICKER_STOPLIST:
            continue
        if len(ticker) < 2:
            continue
        # Bare uppercase MUST be in the universe; $TICKER bypass
        if not dollar_ticker and is_valid_ticker is not None:
            if not is_valid_ticker(ticker):
                continue
        found.add(ticker)
    return found


def _extract_themes(text: str, source: Optional[str] = None) -> set[str]:
    """Match text against theme clusters; return cluster names.

    Wave 14AN (2026-05-30): when a BERTopic model exists at
    data/cross_reference/bertopic_model/ AND NCL_CROSS_REF_BERTOPIC_ENABLED
    is truthy, the learned topic label is added to the hit set alongside
    the keyword-matched clusters. The hardcoded clusters remain as the
    safety net — disabling BERTopic returns to the original behavior.

    Wave 14BJ (2026-05-30): when per-source BERTopic models exist under
    data/cross_reference/bertopic_model/{source}/, they take precedence
    over the global model so reddit / youtube / news / polymarket each
    cluster within their own topic space. The global model remains as
    a fallback when a source has no fitted model.
    """
    if not text:
        return set()
    t = text.lower()
    hits: set[str] = set()
    for cluster, keywords in _THEME_CLUSTERS.items():
        for kw in keywords:
            if kw in t:
                hits.add(cluster)
                break

    # BERTopic enrichment (lazy-loaded; skipped silently if not present).
    if os.environ.get("NCL_CROSS_REF_BERTOPIC_ENABLED", "").lower() in (
        "1", "true", "yes", "on",
    ):
        try:
            from . import bertopic_themes as _bt

            by_source = _get_source_stratified_bertopic()
            fallback = _get_bertopic_themes()
            if by_source or fallback:
                pairs = _bt.classify_themes_for_source(
                    text,
                    source=source or "",
                    loaded_by_source=by_source,
                    fallback=fallback,
                    top_n=1,
                )
                for label, _score in pairs:
                    if label:
                        hits.add(f"bt:{label}")
        except Exception as e:
            log.debug("[cross-ref] bertopic enrichment failed: %s", e)
    return hits


# Lazy-load + cache the BERTopic model so the first signal pays the
# load cost; subsequent calls reuse the in-memory object.
_bertopic_loaded: Optional[dict] = None
_bertopic_lookup_attempted: bool = False
# Wave 14BJ — per-source models cache.
_source_bertopic_loaded: dict[str, dict] = {}
_source_bertopic_lookup_attempted: bool = False


def _get_bertopic_themes() -> Optional[dict]:
    global _bertopic_loaded, _bertopic_lookup_attempted
    if _bertopic_loaded is not None:
        return _bertopic_loaded
    if _bertopic_lookup_attempted:
        return None
    _bertopic_lookup_attempted = True
    try:
        from . import bertopic_themes as _bt

        _bertopic_loaded = _bt.load_bertopic_themes()
    except Exception as e:
        log.debug("[cross-ref] bertopic load failed: %s", e)
        _bertopic_loaded = None
        # Wave 14CS — counter for silent BERTopic load failure
        try:
            from runtime.observability import bump as _bump
            _bump("crossref_bertopic_load_failed", reason=type(e).__name__)
        except Exception:
            pass
    if _bertopic_loaded:
        meta = _bertopic_loaded.get("meta", {})
        log.info(
            "[cross-ref] bertopic themes loaded: n_topics=%s trained_at=%s",
            meta.get("n_topics"),
            meta.get("trained_at"),
        )
    return _bertopic_loaded


def _get_source_stratified_bertopic() -> dict[str, dict]:
    """Wave 14BJ — lazy load per-source BERTopic models."""
    global _source_bertopic_loaded, _source_bertopic_lookup_attempted
    if _source_bertopic_loaded:
        return _source_bertopic_loaded
    if _source_bertopic_lookup_attempted:
        return {}
    _source_bertopic_lookup_attempted = True
    try:
        from . import bertopic_themes as _bt

        _source_bertopic_loaded = _bt.load_source_stratified_bertopic() or {}
    except Exception as e:
        log.debug("[cross-ref] source-stratified bertopic load failed: %s", e)
        _source_bertopic_loaded = {}
    return _source_bertopic_loaded


def _read_recent_signals(window_hours: int) -> list[dict]:
    """Tail agent_signals.jsonl for entries newer than cutoff. Bounded —
    we don't read the whole file (it's rotated to .1/.2 already)."""
    if not SIGNAL_LOG.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    cutoff_iso = cutoff.isoformat()
    out: list[dict] = []
    try:
        # Bounded tail — read last ~5000 lines max
        with open(SIGNAL_LOG, "rb") as fh:
            try:
                fh.seek(-5_000_000, os.SEEK_END)
            except OSError:
                fh.seek(0)
            else:
                fh.readline()  # skip partial
            for raw in fh:
                try:
                    s = raw.decode("utf-8", errors="ignore").strip()
                    if not s:
                        continue
                    d = json.loads(s)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                ts = d.get("timestamp", "")
                if ts and ts >= cutoff_iso:
                    out.append(d)
    except OSError as e:
        log.warning("[cross_ref] read failed: %s", e)
    return out


# ─────────────────────────────────────────────────────────────────────
# Rule evaluation
# ─────────────────────────────────────────────────────────────────────


def _rule_ticker_converge(signals: list[dict]) -> list[PromotedCandidate]:
    """Rule 1: ticker mentioned in ≥2 distinct AWAREBOT sources within window."""
    now_iso = datetime.now(timezone.utc).isoformat()
    # ticker → {source -> [signal_id, title, source]}
    by_ticker: dict[str, dict[str, list[dict]]] = {}
    for s in signals:
        if not _is_intel_source(s.get("source", "")):
            continue
        text = (s.get("title", "") + " " + s.get("content", ""))[:500]
        for ticker in _extract_tickers(text):
            head = (s.get("source", "") or "").split(":")[0].lower()
            by_ticker.setdefault(ticker, {}).setdefault(head, []).append(s)
    out: list[PromotedCandidate] = []
    for ticker, by_source in by_ticker.items():
        distinct_sources = len(by_source)
        if distinct_sources < 2:
            continue
        sigs = [s for siglist in by_source.values() for s in siglist]
        out.append(PromotedCandidate(
            promoted_at=now_iso,
            rule="ticker_converge",
            ticker=ticker,
            convergence_strength=distinct_sources,
            sources=sorted(by_source.keys()),
            signal_ids=[s.get("signal_id", "") for s in sigs][:10],
            sample_titles=[(s.get("title") or "")[:80] for s in sigs][:5],
            window_hours=4,
        ))
    return out


def _rule_theme_converge(signals: list[dict], window_hours: int = 24) -> list[PromotedCandidate]:
    """Rule 2: theme cluster touched by ≥3 distinct sources in 24h."""
    now_iso = datetime.now(timezone.utc).isoformat()
    by_theme: dict[str, dict[str, list[dict]]] = {}
    for s in signals:
        if not _is_intel_source(s.get("source", "")):
            continue
        text = (s.get("title", "") + " " + s.get("content", ""))[:500]
        head = (s.get("source", "") or "").split(":")[0].lower()
        # Wave 14BJ — thread source so per-source BERTopic models score
        # within-source topic spaces (no cross-domain ticker dominance).
        for theme in _extract_themes(text, source=head):
            by_theme.setdefault(theme, {}).setdefault(head, []).append(s)
    out: list[PromotedCandidate] = []
    for theme, by_source in by_theme.items():
        if len(by_source) < 3:
            continue
        sigs = [s for siglist in by_source.values() for s in siglist]
        out.append(PromotedCandidate(
            promoted_at=now_iso,
            rule="theme_converge",
            theme=theme,
            convergence_strength=len(by_source),
            sources=sorted(by_source.keys()),
            signal_ids=[s.get("signal_id", "") for s in sigs][:10],
            sample_titles=[(s.get("title") or "")[:80] for s in sigs][:5],
            window_hours=window_hours,
        ))
    return out


# Wave 14CR — broadcast/sports stoplist for news_trends_double.
# Audit B4.2: rule emitted NBC/NY/NBA/AL/CBS/USA/NCAA from Polymarket
# affiliate-promo article titles ("Polymarket promo code ELITE: Team USA
# World Cup — AL.com"). These are real listed tickers (NY = New York
# Times) but the rule semantics ("news + search = real signal") doesn't
# hold for sports/broadcast outlets being verbatim-extracted from URLs.
_NEWS_TRENDS_BLOCKLIST = frozenset({
    "NBC", "CBS", "ABC", "FOX", "NPR", "PBS", "CNN", "MSNBC", "BBC",
    "NBA", "NFL", "NHL", "MLB", "WNBA", "NCAA", "NCAAB", "NCAAF",
    "USA", "EU", "UK", "UN", "NATO", "OPEC",
    "NY", "AL", "TX", "FL", "CA", "PA", "OH", "NJ", "MA", "VA",
    "NC", "GA", "MI", "WI", "MN", "CO", "OR", "WA", "AZ", "NV",
})


def _rule_news_trends_double(signals: list[dict]) -> list[PromotedCandidate]:
    """Rule 3: ticker hit in BOTH news AND google_trends on same day.

    Wave 14CR hardening (audit B4.2):
      - Min ticker length 3 (was 2 — perfectly overlapped NY/NJ/AL state
        abbrevs and 2-letter sports leagues).
      - Drop tickers in _NEWS_TRENDS_BLOCKLIST (broadcast/sports/macro).
      - Require news source to be reputable — drop ".com" promo-domain
        prefixes like AL.com / Elite Sports NY where the "news" item
        is actually an affiliate code post.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    news_tickers: set[str] = set()
    trends_tickers: set[str] = set()
    sample: dict[str, list[dict]] = {}
    for s in signals:
        head = (s.get("source", "") or "").split(":")[0].lower()
        text = (s.get("title", "") + " " + s.get("content", ""))[:500]
        # Drop affiliate-promo news items (audit B4.2 root cause)
        if head == "news":
            title_lower = (s.get("title") or "").lower()
            if (
                "promo code" in title_lower
                or "affiliate" in title_lower
                or "use code" in title_lower
            ):
                continue
        ticks = _extract_tickers(text)
        # Min-3 length + blocklist gate
        ticks = {
            t for t in ticks
            if len(t) >= 3 and t not in _NEWS_TRENDS_BLOCKLIST
        }
        if head == "news":
            news_tickers |= ticks
            for t in ticks:
                sample.setdefault(t, []).append(s)
        elif head == "google_trends":
            trends_tickers |= ticks
            for t in ticks:
                sample.setdefault(t, []).append(s)
    overlap = news_tickers & trends_tickers
    out: list[PromotedCandidate] = []
    for ticker in overlap:
        sigs = sample.get(ticker, [])
        out.append(PromotedCandidate(
            promoted_at=now_iso,
            rule="news_trends_double",
            ticker=ticker,
            convergence_strength=2,
            sources=["news", "google_trends"],
            signal_ids=[s.get("signal_id", "") for s in sigs][:6],
            sample_titles=[(s.get("title") or "")[:80] for s in sigs][:4],
            window_hours=24,
        ))
    return out


# ─────────────────────────────────────────────────────────────────────
# Dedup + persistence
# ─────────────────────────────────────────────────────────────────────


def _load_today_dedup_keys() -> set[str]:
    """Read today's existing promotions to avoid re-promoting same ticker."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    keys: set[str] = set()
    if not PROMO_LOG.exists():
        return keys
    try:
        with open(PROMO_LOG, "r") as fh:
            for raw in fh:
                try:
                    d = json.loads(raw.strip())
                except json.JSONDecodeError:
                    continue
                if d.get("promoted_at", "")[:10] != today:
                    continue
                if d.get("ticker"):
                    keys.add(f"ticker:{d['ticker']}:{today}")
                if d.get("theme"):
                    keys.add(f"theme:{d['theme']}:{today}")
    except OSError as e:
        log.warning("[cross_ref] dedup read failed: %s", e)
    return keys


def _append(cands: list[PromotedCandidate]) -> None:
    """Append candidates to promotions.jsonl."""
    if not cands:
        return
    try:
        PROMO_DIR.mkdir(parents=True, exist_ok=True)
        with open(PROMO_LOG, "a") as fh:
            for c in cands:
                fh.write(json.dumps(asdict(c), default=str) + "\n")
    except OSError as e:
        log.warning("[cross_ref] append failed: %s", e)


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def scan_and_promote(window_hours_ticker: int = 4) -> list[PromotedCandidate]:
    """Run all 3 rules over recent signals, dedup against today's
    promotions, persist new ones, and return the new ones."""
    sigs_short = _read_recent_signals(window_hours_ticker)
    sigs_long = _read_recent_signals(24)

    candidates: list[PromotedCandidate] = []
    candidates.extend(_rule_ticker_converge(sigs_short))
    candidates.extend(_rule_theme_converge(sigs_long, window_hours=24))
    candidates.extend(_rule_news_trends_double(sigs_long))

    existing = _load_today_dedup_keys()
    new = [c for c in candidates if c.dedup_key() not in existing]

    _append(new)

    if new:
        log.info(
            "[cross_ref] promoted %d (ticker=%d theme=%d news+trends=%d)",
            len(new),
            sum(1 for c in new if c.rule == "ticker_converge"),
            sum(1 for c in new if c.rule == "theme_converge"),
            sum(1 for c in new if c.rule == "news_trends_double"),
        )
    return new


def list_recent_promotions(limit: int = 20) -> list[dict]:
    """Read promotions.jsonl for the iOS NOW surface."""
    if not PROMO_LOG.exists():
        return []
    out: list[dict] = []
    try:
        with open(PROMO_LOG, "r") as fh:
            lines = fh.readlines()
        for raw in reversed(lines[-1000:]):
            try:
                d = json.loads(raw.strip())
                out.append(d)
                if len(out) >= limit:
                    break
            except json.JSONDecodeError:
                continue
    except OSError as e:
        log.warning("[cross_ref] list failed: %s", e)
    return out


__all__ = [
    "PromotedCandidate",
    "scan_and_promote",
    "list_recent_promotions",
    "PROMO_LOG",
]
