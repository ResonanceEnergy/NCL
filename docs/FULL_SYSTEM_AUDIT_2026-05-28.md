# NCL Full System Audit — 2026-05-28

**Audited by**: 5 parallel subagents (one per top-level iOS tab) + system health pass + 4-device deploy verification.
**Brain**: pid 15278 on `100.72.223.123:8800`, 33 named loops firing on cadence, 0 stale (>2hr), costs healthy.
**iOS**: built + installed on all 4 targets (iPhone 16e sim, iPad Pro M5 sim, physical iPhone 15 Pro Max, physical iPad Pro 11). FirstStrike git tree clean (last commit `2ff5215`).

---

## Overall scorecard

| Tab | Sub-tabs | DATA | EMPTY-by-design | BROKEN | Headline finding |
|---|---|---|---|---|---|
| **PORTFOLIO** | 8 | 5 | 3 | 1 | Portfolio sub-tab broker sync dead since 2026-05-27 (`background_sync:false` while adapters report connected) |
| **INTEL** | 9 | 8 | 1 | 0 | All 12 DAILY CONTEXT blocks of Morning Brief Pro confirmed populated; X-Twitter correctly off |
| **MEMORY** | 4 | 4 | 0 | 0* | 3 contract bugs: top-entities limit ignored, fused-search tier/signal_id NULL, pin endpoint rejects non-WC unit_ids |
| **CALENDAR** | 6 | 6 | 0 | 0 | Healthiest tab — all sub-tabs green; only gap is `/watchlist` (lunar-only source) but iOS already uses richer `/todos` |
| **JOURNAL** | 6 | 5 | 0 | 1 | WRITE sub-tab P0: `POST /journal/entry` hangs (same Wave 14E pattern not applied to free-form entries) |

*MEMORY has data but degraded contract.

---

## P0 fixes for Wave 14V

1. **PORTFOLIO broker sync revival** — `portfolio_manager` background sync loop crashed or never started after the 5/27 snapshot. `/portfolio/health.background_sync:false` while `adapters.moomoo.connected:true` + `adapters.snaptrade.connected:true`. User-visible symptom: Portfolio sub-tab shows $0 / "no accounts" despite the brokers being live. Fix: investigate why the 60s sync loop isn't running; check Brain logs for `portfolio_manager` exceptions; likely a silent exception swallowed by the supervisor.

2. **JOURNAL WRITE hang** — `POST /journal/entry` blocks >20s but persists in ~2s. Same root cause as Wave 14E quiz fix that was applied to `morning_quiz` but not to free-form `create_entry`. Fix: wrap `_bridge_to_memory` + `_inject_to_context` calls inside `journal_store.create_entry` with `asyncio.create_task()` for fire-and-forget. Mechanical; ~10 LOC. Cascades to: INSIGHTS will start surfacing real reflections instead of "Recorded 0 journal entries today".

## P1 fixes

3. **MEMORY contract drift** (3 bugs from the audit):
   - `/memory/knowledge-graph/top-entities?limit=50` ignores limit, always returns 20 — backend handler fix
   - `/memory/search/fused` returns `tier:null` + `signal_id:null` on every result — projector isn't lifting source-unit fields
   - `POST /memory/working-context/pin` 404s on any unit_id not already in working_context — breaks pin-from-search and Intel-pin-chip flows; either auto-promote on first pin or change iOS to use a "promote" path

4. **MEMORY top-entities KG noise** — top 3 entities are `$AI` / `Council Report` / `Key Insights`. The latter two are extractor noise that should be filtered (similar to URL/domain blacklist Wave 13).

## P2 / nice-to-have

5. **TIMELINE source-family monoculture** — Wave 14B per-source cap of 5 works, but the 5 sources today are all `awarebot:city_events:*` (calgary/edmonton/oaxaca/san_salvador/asuncion/montevideo/panama_city). Effective monoculture at the source-family level. Fix: extend cap to source-prefix (`awarebot:city_events:` as one bucket → max 5 across all cities combined).

6. **TIMELINE `degraded:true`** — `_load_all_units()` timed out during the audit. Could be transient or a regression of the Wave 13 P0 followup #1 memory-lock fix. Recommend a follow-up watch.

7. **Predictions iOS field-naming** — backend uses `timestamp`, iOS parses `created_at` in `IntelView.swift`. Date cards may render "?". Worth a 1-line fix.

8. **CALENDAR `/watchlist` lunar-only** — CLAUDE.md claims it pulls from 7 subsystems (predictions/scanners/council/journal/paper-trades/portfolio/calendar) but only `lunar_engine` actually contributes. Low impact because iOS uses the richer `/calendar/todos` instead; `/watchlist` is being phased out.

9. **JOURNAL LIFE empty by design** — NATRIX hasn't created any Vision/NorthStar/Goals/Plans yet. Editors exist client-side and POST paths respond; just unused.

10. **`/intelligence/stats` cold-cache race** — first request after idle returns `total_signals:0` then recovers within seconds. Low-impact (iOS auto-recovers).

---

## What's working well (so this doesn't get lost)

- **33 named loops, 0 stale** — scheduler is rock solid
- **Costs healthy**: perplexity $0.12 (12% of $1 cap), openai $0.07 (3% of $2 cap), anthropic well under
- **Morning Brief Pro renders all 12 DAILY CONTEXT blocks** with real data (PORTFOLIO/AGENT/ROTATION/GOAT/BRAVO/OPTIONS/CRYPTO/POLYMARKET/PREDICTIONS/YTC/CONTEXT/TODO_7DAY)
- **Auto-trader is alive**: state.active=true, 4 circuit breakers closed, last tick 1 min ago, 2 ranked strategies (goat lcb 0.158, bravo lcb 0.013)
- **GOAT scanner**: 19 ranked results, 11s scan, NVDA top score 75, IVR gate live
- **BRAVO scanner**: 41 results, NBIS top bravo_score 92 BUY signal
- **Awarebot intel hot**: 290 scored signals across 8 sources scanned 2 min ago; reddit/news/trends/polymarket all <30 min old
- **YTC nightshift**: 43 videos / 23.9 hrs / 506 insights processed
- **Calendar**: full data flow lunar→events→7-city local→todo_generator all green; Skyfield phase 95.3% Waxing Gibbous; live Ticketmaster + Open-Meteo
- **Memory**: 24,215 units / 31K KG nodes / 54K KG edges / 2,281 council-tier units / fused search returning RRF-blended results
- **iOS deploys**: 4/4 devices built green and installed; no provisioning issues

---

## Deploy verification

| Target | UDID | Build | Install |
|---|---|---|---|
| iPhone 16e sim | `9F77D8B9-90B7-49F5-A654-BF6CE34F1D60` | ✅ Debug-iphonesimulator BUILD SUCCEEDED | ✅ |
| iPad Pro 13" M5 sim | `CE298CEE-1125-4090-8847-116691BE501B` | ✅ same .app | ✅ |
| Physical iPhone 15 Pro Max | `00008130-000675C822A2001C` | ✅ Debug-iphoneos BUILD SUCCEEDED | ✅ via devicectl |
| Physical iPad Pro 11 | `00008027-001664301E07002E` | ✅ same | ✅ via devicectl |

---

## Wave 14V backlog (ordered by leverage × cheap × user-visible)

1. JOURNAL WRITE hang — 10 LOC mechanical fix (#2 above)
2. PORTFOLIO sync revival — diagnose + restart `portfolio_manager` background loop (#1)
3. MEMORY pin endpoint — auto-promote-on-first-pin to fix Intel/search chip flows (#3c)
4. MEMORY top-entities limit param wire-up (#3a) + KG noise filter (#4)
5. TIMELINE source-prefix cap (#5)
6. Predictions iOS `created_at` → `timestamp` (#7)
7. MEMORY fused-search tier/signal_id projection (#3b)

The system is in strong shape overall — 1 broken sub-tab, 1 P0 input hang, 3 P1 contract bugs across MEMORY, and several P2 polishes. Everything else is either green or correctly empty by design.
