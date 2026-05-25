# Journal Subsystem — Audit + Morning Quiz + Life Planning Design

**Date**: 2026-05-25
**Trigger**: NATRIX flagged the Journal section as needing audit + redesign — morning quiz, daily/weekly/yearly planning, goals, visions, retirement, daily wisdom.
**Scope**: Wave 14E. Full audit + research + design + ship.

---

## TL;DR

The Journal subsystem is structurally sound but **functionally dormant** — 12 entries over 7 days, 5 of 6 daily reflections had zero entries to reflect on. The reflection engine fires nightly into an empty pool. The fix is not more journal features; the fix is a daily anchor that produces structured input the existing reflection engine can synthesize.

This wave ships three layers:

1. **Morning Quiz** — 7-question structured intention-setting protocol that runs once per morning. Persists answers, pushes themes to working_context, contributes a context block to the morning brief, drops priority items into the calendar todo list, and stocks the journal with one rich entry per day.
2. **Life Plan** — data layer for vision, North-Star goals, OKR-style quarterly objectives, journeys (multi-year arcs), plans (vacations, retirement, major projects). Plain JSON storage + CRUD endpoints. iOS surfaces are read/edit only this wave; LLM synthesis comes in a follow-up.
3. **Daily Wisdom** — curated rotation of stoic / operational / financial / personal aphorisms. Surfaced on the morning quiz screen and the Dashboard. No LLM cost; pure rotation from a YAML/JSON corpus.

The morning quiz is the keystone — once NATRIX answers it daily, the existing reflection engine starts producing real synthesis, the journal becomes a knowledge corpus, and the downstream brief / context / calendar surfaces inherit the intentional signal.

---

## Audit Findings (current state)

### Backend (works mechanically)

| Component | State |
|---|---|
| `runtime/journal/models.py` | 4 Pydantic models: JournalEntry (9 entry types), DailyReflection, JournalInsight, TipEntry. Solid schema. |
| `runtime/journal/store.py` | JSONL-backed JournalStore. CRUD + filters. Idempotent. |
| `runtime/journal/reflection_engine.py` | ReflectionEngine with LLM + template fallback. Bridges reflection to MemoryStore (source=`journal_reflection`, importance=65, BRAIN tier). Auto-extracts tips from `technique`/`best_practice` entries. |
| `runtime/api/routers/journal.py` | 15 endpoints: entry, entries, today, search, tip, tips, tips/contextual, reflection/{date}, reflections, reflect, insights, analytics, stats, context. |
| Scheduler loop | `ncl-journal-reflection` fires at 10pm ET nightly. |

### Data (functionally dormant)

```
journal.jsonl       12 entries  (7 days = 1.7/day; mostly ad-hoc stock tickers)
reflections.jsonl    6 reflections — 5 of 6 say "Recorded 0 journal entries today"
                                     (template fallback fires because there's
                                      nothing to reflect on)
```

The most recent entries are bare titles like "1) Applied Digital $APLD" (twice — dedup not running on entry side). NATRIX is using the journal as a scratch list of tickers, not as a knowledge system. The reflection engine's `summary`, `patterns_noticed`, `questions_raised`, `research_queue`, `tomorrow_focus` fields are all empty 5 nights out of 6.

### Integration (one-way only)

- ✅ reflection → memory_store (writes BRAIN-tier units)
- ✅ technique/best_practice entries → TipEntry corpus
- ❌ journal → working_context (no path)
- ❌ journal → morning brief (the brief doesn't consume journal entries)
- ❌ journal → calendar todos (no path)
- ❌ journal → predictions / trade idea filtering (no path)
- ❌ morning brief / working context → journal prompt (reverse missing too)

### iOS

`Sources/Views/JournalView.swift` is 1,388 LOC with a `JournalSection` enum + `FSSectionPicker` — extensible for new sub-tabs.

---

## Research synthesis

Five threads from web research feed the design:

1. **Morning intention setting boosts task prioritization 40%** per Journal of Applied Psychology. Effective protocols hit four axes: Wake/Refresh, Mind/Body, Fuel, Intentions. Timing matters — before the day's demands hit.

2. **Goal frameworks compose as Russian-doll**:
   - **North Star** — fixed, long-term direction (5+ year)
   - **OKR** — ambitious quarterly objectives + 3-5 measurable key results
   - **SMART** — short, specific, measurable, time-bound tactical goals (weekly/daily)
   - **12-week year** — high-cadence sprint format that compresses annual planning into 12-week cycles
   - Best practice: pick one framework per scope. Mixing within scope kills clarity.

3. **Vision-first retirement planning** — newer paradigm. Ask "what do you want it to LOOK like" before quantifying the dollars. Use vision boards, sketches, narratives. Quantification follows the vision, not the other way around. 30+ year horizon needs health, housing, community, family, hobbies — not just finance.

4. **Habit stacking + micro-habits** — piggyback new behaviors on existing ones. Keep stacked habits to 2-5 minutes. Stanford research: smaller habits → less resistance → higher compliance. The morning quiz is itself a habit stack — anchored to "wake up", takes 2 minutes.

5. **Stoic daily wisdom** — Epictetus pattern: first decide who you want to be, then do what you have to do. AI mentors trained on Stoic / Buddhist / Jungian wisdom provide different lenses. Daily rotation > one big dose. Pair the wisdom with the morning quiz so it lands at decision time.

---

## Morning Quiz design (the keystone)

Seven questions, ~90 seconds to complete. Each answer is short text (single-line) or chip-pick. Persisted to `data/journal/morning-quiz/{YYYY-MM-DD}.json` and as a JournalEntry of new type `MORNING_QUIZ`. Downstream propagation fires once per submission.

### The 7 questions

| # | Question | Type | Downstream effect |
|---|---|---|---|
| 1 | **How am I feeling, 1-10?** + one-word descriptor | int + str | Mood tag on journal entry; informs reflection engine. |
| 2 | **What is the #1 thing I MUST accomplish today?** | str (short) | Top-pinned working-context item. Highest-priority calendar todo for today. IMMEDIATE ACTION candidate in morning brief. |
| 3 | **What are the 2-3 supporting tasks?** | list[str] (≤3) | Calendar todos under today; lower priority than #2. |
| 4 | **What's my market posture today?** | chip pick: `aggressive` / `neutral` / `defensive` / `cash` | Feeds morning brief's risk framing + trade-idea filter (defensive mode → skip futures angle + bias options to spreads). |
| 5 | **What's the ONE question I want answered today?** | str | Added to working-context themes + brief's TODAY'S RESEARCH TOPICS. |
| 6 | **What am I grateful for this morning?** | str (short) | Mood reinforcement; logged for weekly trend. |
| 7 | **What did I learn yesterday I don't want to forget?** | str | Created as a `lesson` JournalEntry, auto-flows into the tips corpus. |

Plus an always-on `notes` free-text field for anything else.

### Schema

```python
class MorningQuiz(BaseModel):
    quiz_id: str = Field(default_factory=...)
    date: str                              # YYYY-MM-DD (operator-local)
    submitted_at: datetime
    mood_score: int                        # 1-10
    mood_word: str                         # one word
    top_priority: str                      # Q2
    supporting_tasks: list[str]            # Q3
    market_posture: str                    # Q4 enum
    research_question: str                 # Q5
    gratitude: str                         # Q6
    yesterday_lesson: str                  # Q7
    notes: str = ""                        # free-form
    # Downstream propagation tracking
    pushed_to_working_context: bool = False
    pushed_to_calendar_todos: bool = False
    pushed_to_journal_entry_id: str = ""
    pushed_to_lesson_entry_id: str = ""
```

### Downstream propagation (the integration)

On successful POST `/journal/morning-quiz`:

1. **Persist** to `data/journal/morning-quiz/{date}.json` + append to `morning-quiz.jsonl` index.
2. **Create JournalEntry** with `entry_type=MORNING_QUIZ`, importance=70, structured content of all 7 answers + notes. ReflectionEngine sees it tonight.
3. **Create lesson JournalEntry** (if Q7 non-empty) with `entry_type=LESSON`, flows into tips corpus automatically.
4. **Push to working_context** — pin Q2 as `morning_quiz:priority` with importance 100. Add Q5 as a context theme. The morning brief picks up the new items via the existing working_context feed.
5. **Push to calendar todos** — Q2 as a high-priority todo for today; Q3 items as medium-priority todos.
6. **Notify morning brief** — if a brief was generated for today before the quiz was submitted, mark it stale and surface the option to regenerate. If brief comes after the quiz, the prompt already sees the new working_context + calendar context naturally.
7. **Update daily-wisdom seen counter** so today's wisdom rotates.

### iOS surface

New `JournalSection.morningQuiz` (first sub-tab when no quiz today; auto-jumps to today's quiz when in-progress; shows past quiz when complete).

```
TODAY'S MORNING QUIZ                         5/25
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WISDOM
"First tell yourself what kind of person you want
to be, then do what you have to do." — Epictetus
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. MOOD             [ 7 ] [ focused      ]
2. TOP PRIORITY     [ Close PLTR Q3 thesis review   ]
3. SUPPORTING       [ Lunch w/ Mark                 ]
                    [ Tax prep block 2pm            ]
                    [ +                             ]
4. POSTURE          ( aggressive | neutral | defensive | cash )
5. ONE QUESTION     [ How does Fed dot-plot rev shift PLTR? ]
6. GRATITUDE        [ Quiet morning before mkt open    ]
7. YESTERDAY        [ Don't anchor on first signal —   ]
   LESSON           [ wait 15 min after open           ]

NOTES (optional)    [                                ]

[SUBMIT — propagates to context, calendar, brief]
```

Past quizzes accessible via small date-picker chip strip.

---

## Life Plan design (vision / goals / journeys / plans)

Lightweight v1 — data layer + CRUD + iOS read/edit. LLM synthesis comes in a follow-up wave.

### Schemas

**`Vision`** — the why. ONE active at a time. Long-form narrative.
```python
class Vision(BaseModel):
    vision_id: str
    title: str                             # "Free, healthy, building"
    narrative: str                         # multi-paragraph
    horizon_years: int                     # default 10
    pillars: list[str]                     # "Financial independence", "Health span", "Creative output"
    created_at: datetime
    last_reviewed_at: datetime | None
    active: bool                           # only one active at a time
```

**`NorthStar`** — annual-scope guiding metric tied to vision.
```python
class NorthStar(BaseModel):
    star_id: str
    year: int
    title: str                             # "Hit $X NAV with health intact"
    measurable: str                        # "$X NAV", "Body composition ratio Y"
    why: str                               # narrative link to Vision
    quarterly_check_ins: list[dict]        # auto-prompted on quarter boundary
```

**`Goal`** — OKR-format with auto-generated SMART weekly tasks.
```python
class Goal(BaseModel):
    goal_id: str
    scope: str                             # "year" | "quarter" | "month" | "week"
    objective: str                         # OKR style — qualitative + ambitious
    key_results: list[KeyResult]           # 2-4 measurable KRs
    parent_goal_id: str | None             # quarter rolls up to year, etc.
    starts_at: date
    ends_at: date
    status: str                            # "active" | "achieved" | "missed" | "carried"
    confidence: int                        # 1-10 weekly self-rating

class KeyResult(BaseModel):
    kr_id: str
    description: str
    target: float                          # numeric target
    current: float                         # last-measured value
    unit: str                              # "$", "%", "count", "days", etc.
    last_updated: datetime
```

**`Journey`** — multi-year arcs that don't fit calendar boundaries (career pivot, illness recovery, building a thing).
```python
class Journey(BaseModel):
    journey_id: str
    title: str                             # "Build NCL into a daily-driver brain"
    narrative: str
    started_at: date
    expected_end_at: date | None
    milestones: list[Milestone]            # chronological waypoints
    status: str                            # "active" | "paused" | "completed" | "abandoned"

class Milestone(BaseModel):
    milestone_id: str
    title: str
    completed_at: datetime | None
    reflection: str = ""                   # what happened at this milestone
```

**`Plan`** — concrete project / vacation / retirement plan with checklist + dates.
```python
class Plan(BaseModel):
    plan_id: str
    title: str                             # "Paraguay trip Aug 2026", "Retire at 55"
    kind: str                              # "vacation" | "project" | "retirement" | "purchase" | "life-event"
    target_date: date | None
    budget_usd: float | None
    checklist: list[ChecklistItem]
    narrative: str = ""                    # vision-first description
    status: str                            # "planning" | "active" | "completed" | "cancelled"

class ChecklistItem(BaseModel):
    item_id: str
    text: str
    done: bool
    due_at: date | None
```

**`DailyWisdom`** — rotation corpus, static-ish data file.
```python
# data/life_plan/wisdom.jsonl — one wisdom per line
{
  "id": "stoic-001",
  "category": "stoic",                    # "stoic" | "operational" | "financial" | "personal" | "creative"
  "text": "First tell yourself...",
  "source": "Epictetus, Discourses 3.23",
  "seen_count": 0,
  "last_seen": null
}
```

### Storage

All life-plan data lives under `data/life_plan/`:
```
data/life_plan/
  vision.json                  # single active vision
  vision-history.jsonl         # archived versions
  north-star/{year}.json
  goals.jsonl                  # all goals, query by scope+status
  journeys.jsonl
  plans.jsonl
  wisdom.jsonl                 # static-ish corpus, seeded with ~50 entries
  wisdom-state.json            # tracks rotation
```

JSONL append-only with periodic compaction. No SQLite for v1 — the dataset is small (dozens of records per type, not thousands).

### Endpoints

```
POST   /life/vision                       # set/update active vision
GET    /life/vision
GET    /life/vision/history

POST   /life/north-star                   # set/update for a year
GET    /life/north-star/{year}
GET    /life/north-star/current

POST   /life/goal                         # create
GET    /life/goals?scope=quarter&status=active
PATCH  /life/goal/{id}                    # update KR current value, confidence, status
GET    /life/goal/{id}

POST   /life/journey
GET    /life/journeys?status=active
PATCH  /life/journey/{id}/milestone       # mark complete

POST   /life/plan
GET    /life/plans?kind=vacation
PATCH  /life/plan/{id}/checklist/{item_id}

GET    /life/wisdom/today                 # rotates daily
GET    /life/wisdom/category/{cat}
POST   /life/wisdom                       # add new wisdom

GET    /life/dashboard                    # one-shot rollup: vision, current goals, active plans, today's wisdom
```

### iOS surfaces

New `JournalSection` cases:
- `morningQuiz` — today's quiz + history strip
- `vision` — single-screen narrative editor + pillars
- `goals` — filtered list by scope, expand to show KRs + confidence slider
- `journeys` — timeline view with milestones
- `plans` — card grid by kind (vacation / project / retirement / life-event)
- `wisdom` — today's wisdom + category-browse + favorites
- existing TIMELINE / TIPS / REFLECTIONS retained

The existing Journal tab becomes the umbrella; the sub-tab picker grows from 3-4 to 8 sections. With more sections we move from a single-row picker to a horizontal-scroll picker (iOS supports this natively).

---

## Integration map (post-ship)

```
                       ┌──────────────────────┐
                       │  MORNING QUIZ (6am)  │
                       └──────────┬───────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
  working_context           calendar todos             journal entry
  - pinned: Q2              - high: Q2 today           - type: MORNING_QUIZ
  - theme: Q5               - med:  Q3 today           - importance: 70
                                                       - flows to reflection
        │                         │                         │
        └─────────────┬───────────┘                         │
                      ▼                                     ▼
            MORNING BRIEF (auto 6am)              REFLECTION (10pm)
            - IMMEDIATE ACTION: Q2                - includes quiz answers
            - RESEARCH TOPICS: Q5                 - patterns across week
            - posture-aware trade ideas           - tomorrow_focus seeded
                                                  - rolls into memory
                      │                                     │
                      └───────────┬─────────────────────────┘
                                  ▼
                        WORKING CONTEXT (next day)
                        ┌──────────────────────┐
                        │  NEXT MORNING QUIZ   │
                        │  - shows yesterday's │
                        │    Q5 / Q7 / posture │
                        │    as context        │
                        └──────────────────────┘

Life Plan layer (orthogonal):
  Vision ── shapes ── NorthStar(year) ── shapes ── Goals(qtr) ── shapes ── Goals(week) ── shapes ── Q2/Q3 picks
  Journeys + Plans ── surface as ── Calendar long-horizon events
  Daily Wisdom ── surfaces on ── Morning Quiz screen + Dashboard
```

---

## Ship plan (this session)

**Phase 4A — Morning Quiz backend** (~600 LOC):
- `runtime/journal/morning_quiz.py` — MorningQuiz model + propagation logic
- `runtime/journal/models.py` — add `MORNING_QUIZ` to EntryType enum
- `runtime/api/routers/journal.py` — add `/journal/morning-quiz/{submit,today,by-date,history,latest}`
- Update Reflection prompt to include MorningQuiz answers
- Wire to working_context + calendar todos

**Phase 4B — Life Plan data layer** (~800 LOC):
- `runtime/life_plan/` new package: models, store, wisdom rotator
- `runtime/api/routers/life_plan.py` — full CRUD for vision/north-star/goals/journeys/plans/wisdom
- Seed `data/life_plan/wisdom.jsonl` with ~50 starter entries

**Phase 4C — iOS Journal redesign** (~1500 LOC):
- `Sources/Models/MorningQuiz.swift`, `Sources/Models/LifePlan.swift`
- `Sources/Network/NCLBrainClient+Journal.swift` extension
- `Sources/Views/Journal/MorningQuizView.swift` (the keystone view)
- `Sources/Views/Journal/VisionView.swift`, `GoalsView.swift`, `JourneysView.swift`, `PlansView.swift`, `WisdomView.swift`
- Modify `JournalView.swift` — extend section enum + picker

**Phase 5 — Validate + deploy**:
- Backend: bounce Brain, smoke-test endpoints, verify quiz → context flow
- iOS: xcodegen + xcodebuild for sim + device, install on all 4 targets
- Single commit per layer (3-4 commits total)
- Push to origin/main

---

## Out of scope (next wave)

- LLM synthesis on goals (auto-generate weekly SMART tasks from quarterly OKRs)
- LLM auto-detection of patterns across journeys
- Goal recommendation engine ("based on your North Star you should…")
- Retirement portfolio simulation (Monte Carlo of current assets against Plan)
- Vision-board image generation (DALL-E/Sora calls to render the vision visually)
- Weekly review wizard (Sunday-night equivalent of morning quiz)
- Yearly review wizard (Dec 30 equivalent)

These are tracked as Wave 14F+ candidates.
