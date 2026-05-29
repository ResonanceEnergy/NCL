# NCL Calendar Lane Mandate v1.0

**Effective**: 2026-05-28
**Operator**: NATRIX
**Authority**: NATRIX-tier (importance 95, procedural memory)
**Lane**: CALENDAR — time-anchored events that affect trading or life this week.
**Owns**: `data/calendar/` (events, lunar cache, local-events per city, todo cache)

---

## 1. Identity

Calendar is the **time-anchored future-facing feed**. It is NOT Intel (Intel is right-now signals, not scheduled events), NOT Memory (Memory is recall of the past), and NOT a notification system (those are scheduled tasks).

Calendar's job is to answer: *"What is happening at a specific time NATRIX should know about?"*

Every datum in this lane has an ISO date or datetime. If a thing has no time anchor, it does not belong here.

## 2. Producers

| Producer | Cadence | Output |
|---|---|---|
| Lunar engine | Continuous | Daily moon phase + cycle context + 60-day forecast |
| Market event calendar | Static yearly + Finnhub on-demand | FOMC, OPEX, quad-witch, VIX expiry, futures roll, economic releases |
| Earnings calendar (yfinance/Finnhub) | Daily cache | Per-ticker earnings dates ± 4 weeks |
| 7-city local-events scanner | Hourly per city | Holidays + Open-Meteo weather + Ticketmaster + curated JSONL |
| Watchlist correlator | On-demand | Correlated to-dos pulled from lunar + predictions + scanners + paper + portfolio + journal |
| Custom event endpoint | NATRIX-direct | `POST /calendar/events` (manually-added events) |

## 3. Event taxonomy

| Category | Examples | Importance default |
|---|---|---|
| **macro_market** | FOMC, NFP, CPI, GDP, treasury auctions | 90 |
| **derivatives_event** | OPEX, quad-witch, VIX expiry, futures roll | 85 |
| **earnings** | Per-ticker earnings dates | 75 (in watchlist) / 50 (otherwise) |
| **lunar_phase** | new / 1st quarter / full / 3rd quarter | 60 |
| **lunar_minor** | crescent / gibbous transitions | 30 |
| **city_cultural** | concerts, festivals, sports for active cities | 50 |
| **city_logistical** | weather alerts, holiday closures | 70 |
| **personal** | birthdays, reminders, planned trades | NATRIX-set |

## 4. Pre-gate rules (write-time)

A calendar event passes the gate when ALL OF:

1. **Has ISO date** (YYYY-MM-DD) or full datetime (UTC)
2. **Has impact level**: `low` / `medium` / `high` / `critical`
3. **Has region scope**: `global` / `US` / per-city / `personal`
4. **Has category** from Section 3 taxonomy
5. **Source provenance** identified (which producer wrote it)

### Pre-gate rejects (specifically excluded)
- **No-date "events"** — if a producer cannot stamp an ISO date, the datum is Intel or Journal, not Calendar
- **Generic logistical events** like "Calgary Transit Hiring event" — these were being scored as intel via Awarebot city_events at authority 0.6. Wave 14W moves city_events to Calendar lane WITH a quality filter that rejects municipal hiring/admin events
- **Ticketmaster scrape garbage** without venue/date

### Quality filter for city_cultural
A city event is accepted only when ALL OF:
- Has venue + date + (artist OR title)
- Title does not match `r"(?i)transit|hiring|administrative|board meeting|city hall"` patterns
- Authority score (per producer config) ≥ 0.4

## 5. Promotion to Memory

Calendar entries **never** auto-promote to Memory. Calendar IS the calendar; if NATRIX wants to recall a past event, he opens the Calendar tab and navigates back. This is by design:

- Stops doubled-counting events as Memory units
- Keeps Memory lane focused on episodic + semantic recall, not "what day was Fed?"

Exception: lunar phase transitions emit Memory units at importance 60 (semantic) for cycle-context queries. Earnings reports likewise emit at importance 70 on the actual report day.

## 6. Consumer contracts

### 6.1 iOS Calendar tab
- **7DAY** ← `GET /calendar/week`
- **30DAY** ← `GET /calendar/month` (excludes first 7 days client-side; the 7DAY tab covers that)
- **TODO** ← `GET /calendar/watchlist` (correlated to-dos)
- **CITIES** ← `GET /calendar/cities` → per-city `GET /calendar/local/{city_id}`
- **MOON** ← `GET /calendar/moon` + `/calendar/energy`
- **SUN** ← `GET /calendar/sun` (or sun block in `/calendar/today`)

### 6.2 Trading agent
- **Read via `calendar_gate`**: per-tick check for FOMC (1d), OPEX/quad-witch (1d), VIX expiry (0d), per-ticker earnings (2d). Blocks new opens within those windows.
- **NEW Wave 14W-E**: `intel_request("calendar.add_followup", when=..., payload=...)` — agent can schedule its own follow-ups (e.g. "re-check this drift cluster at 15:00 ET")
- **NEW Wave 14W-E**: `intel_request("calendar.next_blocker", ticker=...)` — agent can ask "when is the next earnings / OPEX / FOMC?"

### 6.3 Morning brief
- Reads `/calendar/today` for the WHAT TO WATCH section
- Reads economic calendar for direction-indicator block

## 7. Cadence

| Task | When |
|---|---|
| Lunar phase compute | Continuous (on-demand) |
| Market event catalog | Yearly publish + per-event timestamp lookups |
| Earnings cache refresh | Daily 04:00 ET |
| Per-city scanner | Hourly (per `_city_events_loop`) |
| Watchlist correlator | On every `/calendar/watchlist` request |
| Calendar agent (top-level) | `CalendarAgent.run()` continuously |
| Critical/high-impact alerts | Every 10min (`ncl-calendar-alerts`) |

## 8. Governance

| Action | Authority | Mechanism |
|---|---|---|
| Add custom event | NATRIX | `POST /calendar/events` |
| Remove event | NATRIX | `DELETE /calendar/events/{id}` |
| Add city to scanner | NATRIX | env list `NCL_CITY_EVENT_CITIES` |
| Change earnings cache TTL | NATRIX | env `NCL_EARNINGS_CACHE_HOURS` |
| Adjust calendar_gate windows | NATRIX | env `NCL_AT_CAL_FOMC_DAYS`, etc. (already wired) |
| Trigger refresh | NATRIX or agent | `POST /calendar/refresh` |

## 9. Audit + Self-* obligations

The Calendar lane IS:
- **Self-refreshing**: lunar always live-computed, earnings cached + refreshed daily
- **Self-localizing**: 7 cities with own scanners + curated JSONL
- **Self-alerting**: critical/high impact events fire push notifications via central alert dispatcher
- **Self-correlating**: watchlist endpoint pulls from 7 subsystems (lunar/predictions/scanners/council/journal/paper/portfolio/calendar-events) — **today this is mostly lunar-only; Wave 14W TODO: actually wire the other 6 sources**

The Calendar lane IS NOT:
- A news feed (use Intel)
- A scheduled-task system (use scheduler.py)
- A todo-list app (use Journal)
- A logging stream (use Memory)

## 10. Coherent goal (one sentence)

> Tell NATRIX (and the trading agent) what time-anchored events affect trading or life this week — with enough lead time and quality filtering that the calendar is trusted, not skimmed.

If an event has no date, it is not a calendar event. If a calendar event is logistical noise, it doesn't belong here.

## 11. Version + audit

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-28 | NATRIX + NCL Wave 14W-A | Initial Calendar lane mandate; codifies time-anchor requirement + city_events quality filter |

Ingested as procedural memory at importance 95 (NATRIX tier) on every Brain boot.
