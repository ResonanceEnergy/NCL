# NCL Cross-Reference Engine Mandate v1.0

**Effective**: 2026-05-29 (Wave 14X-Y Phase 1B-3)
**Operator**: NATRIX
**Authority**: NATRIX-tier (importance 95, procedural memory)
**Owns**: `runtime/cross_reference/`, `data/cross_reference/promotions.jsonl`

---

## 1. Identity

The Cross-Reference Engine is the **bridge between AWAREBOT and TRADERAGENT camps**. It is a stateless pull-from-disk module that scans the AWAREBOT signal stream every 5 minutes for converging signals and promotes them so TRADERAGENT has something concrete to evaluate without drowning in the loose AWAREBOT pool.

This is the **breakthrough mechanism** NATRIX described:
> *"once running properly one channel isn't going to dominate the rest"* — AWAREBOT stays loose, but only converged signals cross the lane border to PORTFOLIO.

## 2. Mission

> Detect when multiple independent AWAREBOT sources converge on the same ticker or theme, surface the converged candidates for TRADERAGENT, and persist them so the iOS NOW surface can show "HOT 3×" badges.

## 3. Three promotion rules

A signal becomes a `PROMOTED_CANDIDATE` when ANY ONE rule fires:

### Rule 1 — Ticker convergence
Same ticker mentioned in **≥2 distinct AWAREBOT sources** within last 4h.

### Rule 2 — Theme convergence
Shared keyword cluster across **≥3 distinct sources** within last 24h. Initial themes:

- `rate_policy`: FOMC / fed / rate / powell / hawkish / dovish
- `ai_capex`: AI capex / AI infrastructure / nvidia / datacenter / GPU demand
- `energy_supply`: OPEC / crude / oil supply / barrel / WTI
- `crypto_macro`: bitcoin ETF / ETF flows / spot ETF / halving
- `geopolitical`: Taiwan / tariff / sanction / war / ceasefire

### Rule 3 — News+Trends double-verifier
Ticker hit in **BOTH** news (RSS) **AND** google_trends on same day. NATRIX's "if it's in the press AND spiking in search, that's confirmation."

## 4. Dedup

`(ticker, day)` or `(theme, day)` — same hot ticker doesn't re-promote hourly. New promotions only when the day rolls over.

## 5. Output

`data/cross_reference/promotions.jsonl` — append-only. Each entry:

```json
{
  "promoted_at": "2026-05-29T14:32:00Z",
  "rule": "ticker_converge" | "theme_converge" | "news_trends_double",
  "ticker": "XLE" (or null for themes),
  "theme": "energy_supply" (or null for tickers),
  "convergence_strength": 3,
  "sources": ["reddit", "youtube", "polymarket"],
  "signal_ids": [...],
  "sample_titles": [...],
  "window_hours": 4
}
```

## 6. Consumers

| Consumer | What it does |
|---|---|
| iOS Intel→NOW | Show top promotions with "HOT 3×" convergence badge |
| TRADERAGENT scout loop | Poll `list_recent_promotions()` and evaluate against sanity gate |
| Morning Brief executor | Mention top cross-ref hits in "CROSS-REF HOT" strip (Phase 1B onward) |
| Afternoon Debrief | Reflect on today's cross-ref hits + which made money |

## 7. Schedule

5-minute scan loop (`ncl-cross-reference`). Pure pull-from-disk, no LLM cost.

## 8. What it IS NOT

- **NOT** a scorer — it doesn't compete with AWAREBOT's 7-factor composite. It's a convergence detector on top of already-scored signals.
- **NOT** a decision-maker — TRADERAGENT still applies its 15-gate decision chain to promoted candidates.
- **NOT** a memory writer — promotions live in their own jsonl. Promotions earn MemoryStore entries only via the standard memory write-gate (CRITICAL OR x-source ≥ 2).

## 9. AWAREBOT-camp source whitelist

Only signals from camp-AWAREBOT sources count as cross-ref votes:

`reddit`, `youtube`, `youtube_council`, `ytc`, `polymarket`, `google_trends`, `news`, `x_twitter`, `markets`, `yfinance`

Portfolio-side sources (auto_trader, paper, scanner:goat, scanner:bravo) do NOT vote — they're already on the decision side.

## 10. Failure mode

Empty `promotions.jsonl` for a day → no convergences found. Acceptable — means the world genuinely lacked confirmation. Quiet INTEL doesn't break TRADERAGENT (which scans its own scanners independently).

## 11. Version

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-05-29 | Initial mandate. Codifies the AWAREBOT→TRADERAGENT promotion bridge. |
