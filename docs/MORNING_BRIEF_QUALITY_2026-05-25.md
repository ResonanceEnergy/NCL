# Morning Brief Quality Audit + Improvement Plan

**Date**: 2026-05-25
**Trigger**: NATRIX flagged the morning brief as low-quality — narrative repeats top signal, trade ideas feel fabricated, executive summary leaks markdown.
**Scope**: Full audit of `POST /intelligence/morning-brief` end-to-end + research synthesis + 2-phase improvement plan.

---

## TL;DR

The brief has thirteen concrete failure modes, falling into three classes:

1. **Plumbing bugs** (5 issues) — wrong NCL_BASE path drops PORTFOLIO HEALTH; scanner source mismatch leaves GOAT/BRAVO permanently silent; narrow keyword filters leave PRECIOUS METALS / RATES / CRYPTO mostly blank; duplicate `_generate_executive_summary` LLM call in engine.py costs $0.01/brief + injects markdown into a "no markdown" prompt; trade ideas drift toward sector ETFs because the keyword filter latches onto sector names before individual tickers.

2. **Prompt anti-patterns** (4 issues) — "Pink Elephant" negation phrases (`NEVER use mixed signals`, `NEVER use uncertain`) prime the model toward those exact phrases (per recent Anthropic guidance); no signal_id citation requirement so trade ideas can't be source-verified; single-pass 5000-token generation has no plan + no critic + no regenerate; empty sections render as "Signals quiet" stubs instead of being omitted.

3. **Architectural** (4 issues) — no advisor/planner stage (Anthropic's April 2026 Advisor Pattern gives +2.7pt accuracy at -11.9% cost); no constrained JSON output (every field a hallucination risk); no post-generation verifier; the 6,777-char brief is too dense for the iOS Brief sub-tab.

This doc ships **Phase A — surgical** (no model surface changes) in the same session it was written and proposes **Phase B — multi-stage pipeline** for the next wave.

---

## Audit — 13 failure modes from the 2026-05-25 brief

The real `morning-2026-05-25.json` (6,777 chars, generated 13:08 UTC, 928 signals fed):

| # | Symptom | Root cause | Fix class |
|---|---------|------------|-----------|
| 1 | `**HEADLINE DEVELOPMENT**` in exec_summary despite prompt's "Plain text only. Do NOT use markdown asterisks (**)" | Pink Elephant — telling Sonnet 4 not to use `**` makes attention focus on `**`. Plus the prompt is ignored by the `_generate_executive_summary` call in `engine.py:1306` which has its own prompt and DOES emit `**` headers. | Plumbing + prompt |
| 2 | `IMMEDIATE ACTION: No immediate action items — book is quiet.` | Portfolio snapshot read fails (path bug) → no positions to flag → falls through to the stub line. The most important section of the brief (the only one NATRIX needs to act on pre-open) is dead. | Plumbing |
| 3 | `PORTFOLIO HEALTH: Portfolio snapshot unavailable — skipping health read.` | Handler reads `~/dev/NCL/data/portfolio/snapshots.jsonl` via `NCL_BASE` env. `NCL_BASE` is not set, default is `~/dev/NCL`, but the snapshots are at `~/NCL/data/portfolio/snapshots.jsonl` (separate path drift). Even when path is correct, snapshots can be stale — should call `/portfolio/accounts` in-process instead. | Plumbing |
| 4 | `GOAT: No signals from GOAT scanner` and `BRAVO: No signals from Bravo Swing scanner` — every brief | Filter is `"goat" in src or any(k in haystack for k in _GOAT_KEYS)`. Real source string for GOAT signals is `scanner:goat` per `runtime/memory/authority.py:209`. The substring check would catch it, but `_GOAT_KEYS` is hunting for `"goat scanner"`, `" goat "`, etc. inside title+content which the scanner doesn't write. | Plumbing |
| 5 | `PRECIOUS METALS: Signals quiet`, `US RATES (FED): Signals quiet`, `CRYPTO: Signals quiet` | Keyword filter (`_PM_KEYS`, `_RATES_KEYS`, `_CRYPTO_KEYS`) does substring match on title+content. Awarebot ingests crypto from `awarebot:crypto` source, polymarket Fed-meeting odds from `awarebot:polymarket`. The keywords never appear verbatim — should ALSO match on `signal.source.value`. | Plumbing |
| 6 | Trade ideas: XLE, XLU, XLF, XLI, XLK (5 sector ETFs) | The signal feed had AAPL ($81M positive flow), TSLA ($52M), DELL ($32M) in the data per the exec_summary itself — but trade ideas latched onto sector names because options_flow signals tag their TITLE with sector ETF tickers rather than the underlying. Also no portfolio-awareness — NATRIX may already hold AAPL/TSLA. | Prompt + plumbing |
| 7 | No signal_id citation for verifiable claims | Prompt asks for "every ticker must appear in or be directly implied by the signal data" but doesn't enforce signal_id citations. NATRIX can't audit "$499M net premium SPY" claim against source. | Prompt |
| 8 | Single-pass generation, no plan/critic | 5000-token one-shot Sonnet 4 call. No structured plan ("which lanes have real data"), no critique pass, no validation gate. Anthropic April 2026 Advisor Pattern: Opus plans, Sonnet executes — 2.7pt accuracy + 11.9% cheaper. | Architectural |
| 9 | `Portfolio snapshot unavailable` cascades to `ADD TO EXISTING` rule being dead | Trade-idea prompt says "If NATRIX already holds the underlying, say ADD TO EXISTING in THESIS rather than treating it as a new entry." Depends on portfolio context which is empty. | Plumbing (downstream of #3) |
| 10 | `POLYMARKET WATCH: Polymarket quiet` | Polymarket source IS feeding signals (re-enabled May 20 per CLAUDE.md) but `polymarket_signals` filter is `"polymarket" in _src(s)`. Real source is `polymarket` or `intelligence_polymarket` per authority map — should hit. Likely the brief.top_signals list doesn't include them after sort by importance_score — they get filtered out upstream in engine.generate_brief. | Plumbing |
| 11 | Brief is dominated by OPTIONS / OPTIONS FLOW | Unusual Whales options flow has the largest per-signal $ values (concrete dollar amounts that look authoritative). The brief structure rewards concrete numbers, so options crowd out everything else. Need explicit per-source quota in the LLM prompt, not just at the data slicing stage. | Prompt + plumbing |
| 12 | 6,777 chars dense for phone | Brief is intended to be read on iPhone before open. iOS BriefRenderer parses 22 section headers + bullet-style lines. The COMPLETE brief is 22 sections × multiple paragraphs each. Should default to a 2,500-char "phone mode" with an expandable "full brief" drawer for iPad/desktop. | Architectural |
| 13 | Duplicate executive_summary generation: `engine.py:1306` AND `intel/__init__.py:494` both call Sonnet 4 for synthesis | `engine.generate_brief()` calls `_generate_executive_summary()` which does its own 600-token Sonnet 4 call ($0.01). Then `morning-brief` handler calls Sonnet 4 AGAIN at 5000 tokens with overlapping context ($0.04). Engine's exec_summary is then embedded in the morning brief's INPUT, and the morning brief is asked to produce its OWN exec_summary on top — duplicate work + a source of markdown leakage. | Plumbing |

---

## Research synthesis — what the field knows in 2026

**Anthropic Advisor Pattern (April 2026)** — Opus 4.6 as strategic advisor + Sonnet 4.6 as executor. 74.8% vs 72.1% on SWE-bench, -11.9% cost. Powerful for tasks where planning quality > execution speed. Applies cleanly here: a planner pass deciding "which lanes have real signal vs noise, which tickers to focus on, what TODAY's themes are" before the executor writes the brief.

**Claude 4 extended thinking** — Sonnet 4.6 / Opus 4.6 use adaptive thinking; the model decides reasoning depth based on query complexity. **Stop telling the model to "think step-by-step"** — it wastes tokens, the model manages its own budget. Use `<thinking>` tags in few-shot examples to transfer reasoning patterns.

**Pink Elephant effect** — telling an advanced model `NEVER use X` increases X frequency, because attention amplifies the forbidden concept. The current prompt's `NEVER use generic filler: "mixed signals", "uncertain", "varied"` is a literal anti-pattern. **Replace with positive direction**: show what a good sentence looks like, not what a bad one looks like.

**Citation forcing** — every claim attaches a source_id; answers where claims can't be linked to sources are blocked or marked unreliable. Reduces hallucination from 22% → 3.8% in financial Q&A (Self-RAG benchmarks). For the brief: every trade idea, every macro claim, every dollar amount cites a `signal_id` from the supplied data.

**Constrained JSON output** — JSON Schema with `confidence` and `citations[]` arrays prevents structural hallucination. Free-prose brief is hard to verify; JSON output with required fields enables a Critic stage to mechanically validate before shipping.

**Sell-side equity research principles** — lead with the recommendation and WHY; concise summary that maximizes value per word; actionable insights; visible assumptions; explicit risk section. Don't dump data — synthesize it.

**Prompt chaining over mega-prompts** — break into focused, validatable stages. Common patterns: Research → Outline → Draft → Edit → Format. Each stage has a clean input/output contract.

---

## Phase A — Surgical fixes (ship this session)

Seven changes in `runtime/api/routers/intel/__init__.py` (and one in `runtime/intelligence/engine.py`). No model surface changes, no new dependencies, no iOS changes. Each change can be reverted independently.

### A1. Remove Pink Elephant anti-patterns from the prompt
Strip every `NEVER use X` / `Do NOT use X` from the prompt template. Replace with positive examples + "Lead every sentence with a number, ticker, or named event." Per Anthropic 2026 guidance and Pink Elephant research.

### A2. Markdown post-strip
Regex pass on the LLM output before persist: strip leading/trailing `**`, `##`, backtick fences, leftover `# headers` from any line. Tactical hardening since Pink Elephant fix isn't 100%.

### A3. Auto-omit empty sections
Today the prompt forces "if signals don't carry data for a lane, write 'Signals quiet — no actionable read.'" That's stub clutter. Change to: "if a lane has zero matching signals, omit the entire labeled paragraph. Don't substitute a stub." Sections become information-dense.

### A4. Portfolio data via in-process call
Replace the `aiofiles.open(snap_path)` read with `brain.portfolio.get_accounts()` (or whichever in-process API the portfolio router uses). Path drift bug goes away; data is fresh; PORTFOLIO HEALTH renders real numbers.

### A5. Source-based macro lane detection
Extend the lane filters to also match on `signal.source.value`. Examples:
- CRYPTO: signal.source ∈ {`crypto`, `awarebot:crypto`} OR keyword match
- RATES: signal.source ∈ {`polymarket`} AND title contains "Fed/FOMC/rate" OR keyword match
- POLYMARKET: signal.source ∈ {`polymarket`, `intelligence_polymarket`}
Six lanes go from mostly-empty to populated whenever the source is active.

### A6. GOAT/BRAVO scanner source check
Replace the keyword-on-title filter with: `signal.source.value` ∈ {`scanner:goat`, `goat`, ...} per authority.py SOURCE_TIER_MAP. Same for BRAVO. When scanners actually emit signals, they show up.

### A7. Trade-idea signal_id citation requirement
Add to the prompt: "For each STOCK SETUP / OPTIONS PLAY / FUTURES ANGLE, list `SOURCES: [signal_id_1, signal_id_2]` after THESIS. If you cannot cite at least one signal_id from the data feed, write `INSUFFICIENT EDGE` for that block." Pair with a post-parse validator that flags blocks lacking citations (Phase B turns this into a regenerate trigger).

### A8. Drop the duplicate `_generate_executive_summary` engine call
The unified morning-brief prompt now produces the EXECUTIVE SUMMARY section directly. The separate `engine._generate_executive_summary()` call becomes vestigial — it's no longer consumed by the iOS view (which reads `full_brief`) and contributes ~$0.01/brief + a second source of markdown drift. Gate it behind a feature flag (`NCL_LEGACY_EXEC_SUMMARY=1` for back-compat) and skip in the default path.

**Estimated quality lift**: large. The first four changes alone fix the "looks generic" feel; the next three fix the "trade ideas feel fabricated" feel; the eighth saves a buck and reduces markdown leak risk.

---

## Phase B — Multi-stage pipeline (next wave)

Architectural refactor. Same cost (~$0.045 vs current $0.05) but materially higher quality + verifiability.

### B1. PLANNER stage (Sonnet 4.6, ~300 tokens, JSON output)
Receives a CONDENSED signal summary (per-source counts + top-3 by score). Outputs:

```json
{
  "mode": "full" | "short" | "no-edge",
  "themes": ["energy distribution divergence", "tech accumulation"],
  "active_lanes": ["OIL", "BONDS", "CRYPTO"],
  "skipped_lanes": ["PRECIOUS METALS", "RATES"],
  "focus_tickers": ["XLE", "AAPL", "TSLA"],
  "portfolio_alerts": [{"ticker": "PLTR", "concern": "near stop"}],
  "research_topics": [{"topic": "...", "why": "..."}, ...]
}
```

Cost: ~$0.001. Validates upstream: if `mode == "no-edge"` → ship a 200-char "quiet day, no actionable read" instead of fabricating content.

### B2. EXECUTOR stage (Sonnet 4.6 extended thinking, ~3500 tokens, JSON output)
Receives the plan + the signal data filtered per the plan. Each section is JSON with `text` + `citations: [signal_id]`. Trade ideas have explicit `sources: [signal_id]` array.

### B3. CRITIC stage (Haiku 4.5, ~200 tokens)
Mechanical validation pass:
- Every trade idea has ≥1 signal_id in `sources[]`
- No `signal_id` is fabricated (cross-check against the planner's data feed)
- No markdown characters in any `text` field
- No empty `text` fields
- No section described as "quiet" / "unavailable" / "no actionable read"

Returns `{"ship": bool, "reasons": [str]}`. Cost: ~$0.0005.

### B4. Conditional regenerate
If `ship: false` and there's budget remaining, regenerate ONLY the failed sections with the critic notes injected as context. Cap at one regenerate per brief (~$0.01 extra worst case).

### Cost comparison
| Mode | Stage | Tokens | Cost/brief |
|------|-------|--------|------------|
| Current | Single-pass Sonnet 4 | 5000 out / 3000 in | $0.05 |
| Current + engine exec_summary | + Sonnet 4 600tok | — | +$0.01 |
| Phase A | Single-pass Sonnet 4 (no duplicate) | 4500 out / 3000 in | $0.045 |
| Phase B | Planner + Executor + Critic + (optional regen) | 300 + 3500 + 200 + (optional 800) | $0.039–$0.049 |

Phase B is **cost-neutral or cheaper** than current AND materially higher quality.

### iOS implications for Phase B
Switching to JSON output requires iOS BriefRenderer changes — either a new JSON consumer or a "render JSON to the same plain-text format BriefRenderer already parses" backend shim. The shim is the lower-risk path.

---

## Wave tag

`Wave 14C — Morning Brief Quality (Phase A surgical)`. Phase B as `Wave 14D` after Phase A bakes for a few days.

---

## File-level change list (Phase A)

- `runtime/api/routers/intel/__init__.py` — rewrite morning-brief handler section: prompt template (A1, A3, A7), portfolio inline call (A4), macro lane source-aware filters (A5, A6), markdown strip (A2), drop engine exec_summary consumption (A8)
- `runtime/intelligence/engine.py` — gate `_generate_executive_summary` behind `NCL_LEGACY_EXEC_SUMMARY` env (default off) (A8)
- `docs/MORNING_BRIEF_QUALITY_2026-05-25.md` — this doc

## Validation plan

1. ast parse + pyflakes
2. Trigger fresh morning brief via `POST /intelligence/morning-brief`
3. Verify: no `**`, no `## `, no `Signals quiet` stubs, PORTFOLIO HEALTH has real position data, trade ideas cite signal_ids, GOAT/BRAVO render real signals when source is active
4. Compare brief length: should be similar or shorter (omitted stubs)
5. Compare brief cost in `/system/costs/today` — should be ~$0.04 vs ~$0.05
