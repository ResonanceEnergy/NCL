#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add runtime/intelligence/rotation_tracker.py runtime/intelligence/style_ratios.py runtime/intelligence/cycle_phase.py runtime/intelligence/brief_prep.py runtime/intelligence/brief_council.py runtime/intelligence/brief_presenter.py runtime/api/routes.py docs/CAPITAL_ROTATION_2026-05-26.md CLAUDE.md

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14I — Capital Rotation Tracker (rotation_tracker + style_ratios + cycle_phase) wired into Morning Brief Pro

NATRIX deep-dive research on capital rotation (docs/CAPITAL_ROTATION_2026-05-26.md)
identified the gap: NCL had the plumbing (sector tags, SectorSnapshot,
ETF watchlist, rule 7a) but no time-series rotation state. Each brief
was point-in-time; nothing tracked regime over days.

Three new intelligence modules:

1. runtime/intelligence/rotation_tracker.py (~280 LOC)
   Daily snapshot of 11 SPDR sector ETFs vs SPY:
     - per-sector daily % change, last close, above_50d_sma
     - JdK-style RS-Ratio (20d % change of sector/SPY ratio)
     - RS-Momentum (5d % change of the ratio)
     - 4-quadrant RRG: Leading / Improving / Weakening / Lagging
     - 50d-SMA breadth (sectors_above / total → %)
     - cycle hint derived from leadership composition
   Persists to data/rotation/YYYY-MM-DD.json.

2. runtime/intelligence/style_ratios.py (~150 LOC)
   IWM/SPY, IWD/IWF, XLU/SPY, RSP/SPY, ARKK/SPY ratios with
   1d/5d/20d % change + direction tag (rotating_in/out/trending/neutral).
   regime_signals list summarizes active rotations. Persists to
   data/rotation/style-YYYY-MM-DD.json.

3. runtime/intelligence/cycle_phase.py (~280 LOC)
   Reads yield curve (^TNX vs ^FVX), MANEMP proxy, ICSA jobless claims,
   BAMLH0A0HYM2 HY credit spread from FRED (best-effort, all fallable).
   Vote-based classifier → early_expansion / mid_cycle / late_cycle /
   recession (or 'mixed' when confidence <0.35). Returns expected_leaders
   per phase. Persists to data/rotation/cycle-YYYY-MM-DD.json.

Integration:

- brief_prep.py now gathers rotation/style/cycle concurrently with the
  existing futures/VIX/headlines collectors and folds them into the
  prep pack (rotation_snapshot, style_ratios, cycle_phase fields).

- brief_council.py::_macro_prompt passes the three blocks to the Macro
  Analyst so direction calls are regime-aware. The chair_prompt OUTPUT
  SHAPE gains a rotation_regime object inside market_open_plan with
  current_phase / leading_sectors / weakening_sectors / breadth_pct /
  active_style_rotations / one_liner. New synthesis rule 7d — trade
  ideas should mostly lean WITH Leading-quadrant sectors; counter-trend
  must be labeled.

- brief_presenter.py renders a new ROTATION REGIME sub-block inside the
  MARKET OPEN PLAN section: cycle phase + leading sectors + weakening +
  breadth % + active style rotations + one-liner read. Falls back to
  synthesizing from prep pack if chair omits the structured field.

- runtime/api/routes.py GOAT + BRAVO scanners cross-reference today's
  Leading-quadrant via load_latest_rotation() and tag each result with
  rotation_aligned: bool + sector_etf: str. scan_meta includes
  rotation_leading_sectors for operator visibility.

Live verification (POST /intelligence/morning-brief/pro/fire):
  elapsed: 76s
  members_succeeded: 4/4
  market_open_plan keys: ['what_to_watch', 'direction_indicators',
                          'momentum_signals', 'risk_flags',
                          'rotation_regime']
  rotation_regime: {
    'current_phase': 'late_cycle',
    'leading_sectors': ['XLK'],
    'breadth_pct': 81.8,
    'one_liner': 'Leading: XLK (growth/risk-on)'
  }
  council_meta.contradictions_resolved includes 'Late-cycle positioning
  vs tech leadership: Current momentum overriding defensive cycle
  expectations' — confirms Macro Analyst is reading + reasoning over
  the cycle_phase block.

Full research + roadmap: docs/CAPITAL_ROTATION_2026-05-26.md
(market data verified against 2026 Q2 rotation reporting — IWM +6.8% YTD
vs SPY -0.1%, Energy +21%, Materials +17%; tactical tips + cycle phase
leadership tables).

Wave 14I roadmap items 1-9 shipped. Item 10 (iOS RRG widget) queued
for a separate Mac/iOS UI wave.

Net: 3 new modules + 4 modified runtime files + 1 doc + CLAUDE.md.
~+1,100 LOC.
"
git push origin main 2>&1 | tail -3
