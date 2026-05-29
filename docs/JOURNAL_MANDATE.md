# NCL Journal Lane Mandate v1.0

**Effective**: 2026-05-28
**Operator**: NATRIX
**Authority**: NATRIX-tier (importance 95, procedural memory)
**Lane**: JOURNAL — NATRIX's voice + reflections + life plan + daily ritual.
**Owns**: `data/journal/` (entries, morning-quiz, weekly-review, yearly-review, tips, reflections), `data/life_plan/`

---

## 1. Identity

Journal is NATRIX's **first-person lane**. Everything that comes out of this lane carries NATRIX's voice or is a deliberate reflection on behalf of NATRIX. Journal is NOT a generic notes app (Memory holds notes), NOT an Intel digest (Intel holds outside-world signals), and NOT a calendar of events (Calendar holds those).

Journal's job is to answer: *"What did NATRIX think / feel / commit to / reflect on today, this week, this year?"*

NATRIX's voice is the source of truth. Auto-reflections (Sonnet 4 nightly) and quiz responses are first-class but secondary; they exist to support NATRIX's own writing, not replace it.

## 2. Producers

| Producer | Cadence | Output |
|---|---|---|
| NATRIX direct write | On-demand via iOS | Free-form `note` / `idea` / `decision` / `commitment` / `reflection` entries |
| Morning quiz scheduler | 06:00 ET daily + 12:00 ET nudge | 7-question structured entry |
| Weekly review wizard | Sunday 18:00 ET | 7-question weekly reflection |
| Yearly review wizard | Dec 28 | 7-question yearly reflection |
| ReflectionEngine | 22:00 ET daily | Sonnet 4 LLM synthesis of today's entries |
| LifePlan editors | On-demand | Vision / NorthStar / Goal / KR / Plan / Milestone records |
| Monthly review (auto-trader) | 1st of month 06:00 ET | Reflection-type entry summarizing strategy scorecard |
| Tips system | NATRIX direct | Personal trading tips / mantras / reminders |

## 3. Entry types

| Entry type | Default importance | Description |
|---|---|---|
| `note` | 50 | Free-form jotting |
| `idea` | 60 | Trade idea, project concept, hypothesis |
| `decision` | 75 | Recorded decision NATRIX made |
| `commitment` | 80 | What NATRIX commits to (high importance — survives daily eviction) |
| `reflection` | 70 | Considered look-back |
| `morning_quiz` | 80 | Today's anchor responses |
| `weekly_review` | 85 | Sunday wizard |
| `yearly_review` | 95 | Dec 28 wizard |
| `tip` | 60 | Personal mantra / reminder |
| `daily_synthesis` | 70 | Nightly ReflectionEngine output |
| `monthly_review` | 85 | Auto-trader strategy reflection |

## 4. Pre-gate rules (write-time)

The Journal lane is the **most permissive** of the 5 lanes by design — NATRIX's voice always passes. Specific rules:

1. **Free-form NATRIX writes always pass** (no rejection, no length minimum)
2. **Auto-generated entries** (reflection / monthly / quiz) gated by `entry_type` enum
3. **LifePlan structured writes** require schema validation (Vision/Goal/KR/Plan models)
4. **Importance floor 50** for memory-bridge — entries below 50 stay in Journal lane only, do not echo to Memory
5. **Quiz template carry-forward**: yesterday's top_priority + research_question carry forward if today's quiz is empty (Wave 14E)
6. **PII redaction respects NATRIX context**: NATRIX writing about his own life is not redacted; redaction applies to attempts to write about other people's PII

## 5. Promotion to Memory

The Journal → Memory bridge fires when:

- **Entry importance ≥ 50** → echo to Memory with same content + tags + entry_type
- **`commitment` type** → always to Memory at importance 85
- **`yearly_review` type** → always to Memory at importance 95 (NATRIX-tier)
- **Daily ReflectionEngine output** → Memory at importance 70 (BRAIN-tier)

The bridge is fire-and-forget (Wave 14V V1 fix — `asyncio.create_task` so journal write returns instantly).

## 6. Working context auto-pin

Specific items auto-pin to working context (Memory→Intel→AGENDA path):

- **Morning quiz Q2 (top_priority)** → pinned at importance 100 (NATRIX-tier) as `morning_quiz:priority`
- **Morning quiz Q5 (research_question)** → added as research theme to brief executor
- **Active commitments** → pinned through their stated end-date

This is how Journal informs everything else without violating "one primary lane" rule — the data lives in Journal; pinning is a Memory-lane concern.

## 7. Consumer contracts

### 7.1 iOS Journal tab
- **QUIZ** ← `GET /journal/morning-quiz/today` (+ submit form if not done)
- **LIFE** ← `GET /life/dashboard` + Vision/Goal/Plan editors
- **WRITE** ← `POST /journal/entry` (free-form)
- **SEARCH** ← `GET /journal/search?q=...`
- **TIPS** ← `GET /journal/tips`
- **INSIGHTS** ← rollup of Today / Reflect / Analytics

### 7.2 Trading agent
- **Read via working_context_gate**: agent sees morning_quiz Q2 priority + research themes pinned at importance 100
- **NEW Wave 14W-E**: `intel_request("journal.posture")` — agent can ask "what's NATRIX's stated trading posture today?"

### 7.3 Morning brief
- Reads last night's `daily_synthesis` for context
- Reads pinned commitments + this-week's quiz responses for direction context

### 7.4 Monthly review (auto-trader)
- Writes its OWN entry as `monthly_review` type
- Imports NATRIX's other journal entries from the month to inform the narrative

## 8. Cadence

| Task | When |
|---|---|
| Free-form write | On-demand via iOS |
| Morning quiz prep | 00:05 ET (template carries forward yesterday's posture) |
| Morning quiz nudge #1 | 06:00 ET if not submitted |
| Morning quiz nudge #2 | 12:00 ET if not submitted |
| Weekly review wizard | Sunday 18:00 ET |
| Yearly review wizard | Dec 28 |
| ReflectionEngine | 22:00 ET daily |
| LifePlan goal synthesis | On `POST /life/goal/{id}/synthesize-weekly` |
| Vision board image generation | On `POST /life/vision/board/generate` |
| Monthly review | 1st of month 06:00 ET (separate cron) |
| Memory bridge | Continuous fire-and-forget on every write |

## 9. Governance

| Action | Authority | Mechanism |
|---|---|---|
| Write entry | NATRIX only | `POST /journal/entry` (importance defaults from type) |
| Edit entry | NATRIX | `PUT /journal/entry/{id}` |
| Delete entry | NATRIX | `DELETE /journal/entry/{id}` (rare — better to add a correction note) |
| Set Vision | NATRIX | `POST /life/vision` |
| Set Goal | NATRIX | `POST /life/goal` |
| Generate vision board | NATRIX | `POST /life/vision/board/generate` (~$0.04 OpenAI gpt-image-1) |
| Adjust quiz template | NATRIX | `POST /journal/morning-quiz/template` |
| Disable nudges on weekends | NATRIX | env `NCL_QUIZ_NUDGE_WEEKENDS` |

## 10. Audit + Self-* obligations

The Journal lane IS:
- **NATRIX-voice-primary**: every entry tagged with author (NATRIX vs auto) so the source of voice is auditable
- **Self-reflecting**: nightly Sonnet 4 synthesis (`daily_synthesis`)
- **Self-prompting**: morning quiz nudges via ntfy until answered
- **Self-tracking commitments**: commitments survive day rollover until marked done
- **Memory-bridging**: importance ≥ 50 entries echo to Memory automatically (fire-and-forget)

The Journal lane IS NOT:
- A notes app for arbitrary data (use Memory)
- A scheduling tool (use Calendar)
- A monitoring stream (use Ops/SystemMonitor)
- A morning brief replacement (brief is Intel-lane production from world data; journal is NATRIX's own voice)

## 11. Coherent goal (one sentence)

> Capture NATRIX's voice + reflections + life plan + daily ritual — and surface the most important pieces (today's priority, active commitments, research themes) to the rest of the system without losing NATRIX's authorship.

If an entry has no author voice or LLM-supported reflection on NATRIX's own activity, it does not belong in Journal.

## 12. Version + audit

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-28 | NATRIX + NCL Wave 14W-A | Initial Journal lane mandate; codifies voice-primacy + memory bridge rules |

Ingested as procedural memory at importance 95 (NATRIX tier) on every Brain boot.
