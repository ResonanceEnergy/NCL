# NCL Brain Audit

Scope: `runtime/ncl_brain/{brain.py,council.py,models.py,__init__.py}` cross-referenced against `runtime/api/routes.py`, `runtime/memory/`, `runtime/intelligence/`, `runtime/awarebot/`, `runtime/paperclip_adapter/`, `runtime/governance/`. No `runtime/mandates/` directory exists — mandate logic lives entirely in `brain.py` + `models.py`.

---

## 1. Module Overview

**brain.py (1198 lines).** `NCLBrain` is the top-level service. It owns a `CouncilEngine`, `MemoryStore`, `Scanner`, `FuturePredictor`, and `PaperclipClient`. It implements the Strike-Point pump lifecycle (intake → council → mandate-draft → human approval gate → NCC dispatch) plus MWP stage handoffs (`_mwp_intake` … `_mwp_review`, lines 471–583). Public entry points called from routes.py: `init`, `shutdown`, `health_check`, `receive_pump_prompt`, `approve_and_dispatch`, `reject_pump`, `spawn_council_session`, `create_mandate`, `get_mandate`, `list_mandates`, `complete_mandate`, `query_memory`, `receive_feedback`, `run_awarebot_scan`, `run_prediction`, `_log_event` (private, leaked across the trust boundary). State: in-memory `mandates`, `council_sessions`, `_pending_dispatches` dicts; persistence via `events.ndjson`, `mandates.json`.

**council.py (1219 lines).** `CouncilEngine` runs the Hybrid Delphi-MAD 3-round debate (POSITION → REBUTTAL → CONVERGENCE → SYNTHESIS). Six members (Claude/chair, Grok, Gemini, Perplexity, GPT, Copilot) with role personas in `ROLE_SYSTEM_PROMPTS` (lines 57–101). Quorum check after rounds 1 & 2; failure halts and emits a Paperclip alert. Synthesis is Claude-prompted JSON; falls back to regex on parse failure. Direct `httpx` calls to all five vendor APIs plus Ollama fallback. Paperclip integration (issue create, cost-events, synthesis update, low-consensus approval, quorum alert) is bypassed when `_paperclip` is None. Public surface: `spawn_session`, `run_debate`, `close`. Routes never call this directly — only through `brain.spawn_council_session`.

**models.py (479 lines).** Pydantic v2 models. Enums: `EventType`, `PillarType`, `MandateStatus` (with `valid_transitions()` state machine and `can_transition_to`), `CouncilStatus`, `CouncilMember`, `CouncilRole`. Records: `PumpPrompt`, `Mandate` (with `transition_to` enforced state machine + audit trail), `DebateRound`, `ConsensusScore`, `CouncilSession`, `FeedbackReport`, `MemUnit`, `InsightSignal`, `CouncilOutput`. Event-schema-v1 lives in `NCLEvent` + `ProvenanceEnvelope` (lines 59–195) with `quick()` factory. Routes import `PumpPrompt`, `Mandate`, `CouncilSession`, `FeedbackReport`, `PillarType`, `MandateStatus`, `NCLEvent`, `EventType`.

**\_\_init\_\_.py (5 lines).** Version metadata only — no re-exports.

---

## 2. Behavior Map — `NCLBrain` public methods

Thinking / research:
- `run_awarebot_scan(queries)` (979) — fan-out scan_x + scan_youtube; reddit dropped silently.
- `run_prediction(topic)` (1026) — gathers memory tags, hand-rolls a single dummy `InsightSignal`, calls `predictor.predict`.

Council / debate orchestration:
- `spawn_council_session(topic, prompt, members)` (735) — converts string member names → enum, calls `council_engine.spawn_session` then `run_debate`, persists consensus into memory.
- `_build_council_prompt` (585), `_extract_mandates_from_council` (608) — regex extractor for PILLAR/TITLE/OBJECTIVE/PRIORITY blocks.
- MWP stage writers `_mwp_intake/_mwp_analysis/_mwp_synthesis/_mwp_mandate_draft/_mwp_review` (498–583).

Memory:
- `query_memory(tags, importance_threshold, days_back)` (942) — wraps `memory_store.search_units`.
- (No CRUD on memory units exposed at brain level — routes call `brain.memory_store.create_unit` directly.)

Intelligence / feedback:
- `receive_feedback(feedback)` (912) — logs + creates a memory unit; returns report_id.

Mandates / lifecycle:
- `receive_pump_prompt(prompt, auto_flow)` (198) — main strike flow; produces `PENDING_APPROVAL` mandates and stops.
- `approve_and_dispatch(pump_id, mandate_ids?, modifications?)` (341) — promotes to ACTIVE, calls `_dispatch_to_ncc`.
- `reject_pump(pump_id, reason)` (429) — marks all CANCELLED.
- `create_mandate(...)` (792), `get_mandate` (856), `list_mandates` (868), `complete_mandate` (890).
- `_dispatch_to_ncc(mandates)` (667), `_set_budget_policies` (149), `_persist_mandates` (1194), `_load_state` (1183).

Lifecycle:
- `init()` (123), `shutdown()` (1108), `health_check()` (1083), `_log_event(...)` (1115).

---

## 3. Risks & Findings (severity-ordered)

### CRITICAL — `routes.py` calls `brain.process_pump()` which does not exist
**Where:** `routes.py:3185` and `routes.py:3295`.
**What:** Both `/intelligence/escalate` paths invoke `await brain.process_pump(pump)`. `NCLBrain` has no such method; the public method is `receive_pump_prompt`. The first call site bubbles into a generic warning ("Pump submission failed: {e}") and silently drops the pump on the floor — escalations from the intelligence engine never reach council. The second call site swallows with a bare `except Exception: pass`.
**Fix:** Rename to `receive_pump_prompt(pump, auto_flow=True)`. While there, kill the bare `except` at 3296 and log the exception.

### CRITICAL — `ConsensusScore` constructed with non-existent fields
**Where:** `council.py:372–377`, `council.py:437–442`.
**What:**
```
session.consensus_score = ConsensusScore(
    agreement_pct=0.0, confidence=0.0, threshold_met=False, reason="Quorum not met"
)
```
`ConsensusScore` (models.py:355–363) has neither `confidence` nor `reason`. With Pydantic v2 default config this raises on extra kwargs (or at minimum drops them silently). Both quorum-failure paths therefore raise during construction, masking the actual quorum failure with a `ValidationError` and short-circuiting the Paperclip alert path.
**Fix:** Either add `confidence: float = 0.0` and `reason: Optional[str] = None` to `ConsensusScore`, or change to `confidence_weighted=0.0` and stuff the reason into `session.synthesis` (already done above).

### CRITICAL — `routes.py` calls non-existent `memory_store.query`
**Where:** `routes.py:1003`.
**What:** `await brain.memory_store.query(days_back=1, limit=5)`. `MemoryStore` exposes `search_units(tags, importance_threshold, days_back)` — no `query`, no `limit`. Wrapped in `except: pass` so the dashboard "recent_units" panel silently shows empty.
**Fix:** `await brain.memory_store.search_units(days_back=1)` and slice `[:5]`. Remove the bare `except`.

### HIGH — Mandate state machine bypassed; status mutated directly
**Where:** `brain.py:395, 449, 902`.
**What:** `models.Mandate.transition_to()` (models.py:297–320) enforces valid transitions and writes audit history. Brain instead does `mandate.status = MandateStatus.ACTIVE / CANCELLED / COMPLETED` and skips the validator. This means: (a) you can move COMPLETED→ACTIVE without a peep; (b) `status_history` is never populated; (c) the MWP governance state machine is decorative.
**Fix:** Replace direct assignments with `mandate.transition_to(new_status, reason=...)`; wrap in try/except and log on `ValueError`.

### HIGH — Race condition on `mandates`, `council_sessions`, `_pending_dispatches`
**Where:** `brain.py:119–121`, all read/write sites.
**What:** Three plain dicts, mutated from concurrent FastAPI request handlers and from `receive_pump_prompt` which spans many `await` points. `_persist_mandates` reads `self.mandates.values()` mid-flight; if another request creates a mandate while the JSON dump is iterating, you get `RuntimeError: dictionary changed size during iteration`. Likewise `_pending_dispatches[pump_id]` and `del _pending_dispatches[pump_id]` are interleaved without a lock.
**Fix:** Add an `asyncio.Lock` around mandate/pending mutations and persistence; or snapshot via `list(self.mandates.values())` before serialization.

### HIGH — Quorum detection is sloppy and order-dependent
**Where:** `council.py:353–356`, `council.py:418–421`.
**What:**
```
if "unavailable" in resp.lower() or "[" in resp and "]" in resp and "unavailable" in resp.lower()
```
Operator precedence: `or` binds looser, so the second branch needs `(... and ...)` parens. As written, the first `"unavailable" in resp.lower()` already short-circuits, making the bracket check dead code. Worse, any legitimate response that contains the word "unavailable" (e.g., a response discussing service availability) trips the quorum failure. False-positive quorum aborts in production.
**Fix:** Use the canonical sentinel `f"[{member.value} unavailable — both API and Ollama failed]"` from `_get_member_response_safe:554`. Match `resp.startswith(f"[{member} unavailable")` exactly.

### HIGH — API keys are accepted via `__init__` and forwarded as-is to outbound HTTP, but NCL has no governance/policy gate
**Where:** `brain.py:36–53`, `council.py:249–275`.
**What:** `NCLBrain` and `CouncilEngine` take six API keys as constructor args; secrets pass through several intermediate dicts and are reachable via `getattr(brain.council_engine, "claude_api_key")`. No redaction in logs (the Paperclip auto-gen token in `routes.py:91–93` already leaks at WARN level — same pattern is reachable here). `_log_event` payload is whatever the caller passes — there is no allow-list for what gets persisted to `events.ndjson` or shipped to Paperclip.
**Fix:** (1) Don't accept keys as constructor args — read from a `Secrets` provider so they're never on the object. (2) Add a `_redact()` filter for log payloads. (3) The auto-gen token at routes.py:89 must never be logged.

### HIGH — Pydantic models don't enforce what brain.py assumes
**Where:** `models.py:266–269` vs `brain.py:226, 644, 661`.
**What:** `PumpPrompt.urgency` is a free-form `str`, but brain code branches on the literal values `"critical"`, `"high"`, `"normal"`. A typo in iOS Shortcut (`"crtical"`) silently routes to default priority 5. Likewise `PumpPrompt.source` is a free-form string that becomes a tag and a Paperclip actor key.
**Fix:** Promote `urgency` to a `Literal["low","normal","high","critical"]` or a `UrgencyLevel` enum; same for `source` (or at least pin a regex via Pydantic `Field(pattern=...)`).

### HIGH — Hard-coded URLs and ports scattered across the module
**Where:** `brain.py:40` (`anthropic_base_url` default), `brain.py:50` (`ollama_host` default), `brain.py:51–52` (paperclip), `brain.py:164` (`PAPERCLIP_URL` env w/ literal default), `brain.py:672–673` (NCC_HOST/NCC_PORT env w/ defaults), `council.py:601, 621, 639, 659, 723` (every vendor URL is a literal in code), `council.py:1005, 1043, 1083, 1138, 1182` (paperclip URL re-resolved 5 times via `os.getenv` instead of being passed in once).
**Fix:** Centralize in `api/config.py`. Pass `paperclip_url`, `ncc_url`, `ollama_url` into `CouncilEngine.__init__`. Resolve env once at startup, not per-call.

### MEDIUM — Mandate persistence is full-rewrite and racy
**Where:** `brain.py:1194–1198`.
**What:** `_persist_mandates` opens `mandates.json` in `"w"` mode and dumps everything. No tmpfile + rename — power loss or concurrent write truncates the file. The mandates store can also grow unbounded (no eviction, no archival), at which point every `create_mandate` rewrites the whole file.
**Fix:** Write to `mandates.json.tmp` then `os.replace()`. Combine with the lock from "Race condition" above. Long term: NDJSON append.

### MEDIUM — Synthesis JSON parse silently masks structured data
**Where:** `council.py:799–832`.
**What:** When Claude returns valid JSON the chair re-stringifies it into a markdown-ish text block; `_extract_insights` then regex-parses *that* (council.py:909–979). If anyone updates the synthesis prompt, the round-trip silently truncates lists at 15/10. Also: `except (json.JSONDecodeError, TypeError, KeyError)` masks `AttributeError` from `parsed.get(...)` if Claude returns a JSON array instead of an object.
**Fix:** Keep the parsed dict on `session.synthesis_json` (new field); have `_extract_insights` consume the dict directly and only fall back to regex when the dict is missing.

### MEDIUM — Bare `except: pass` swallowing audit-critical errors
**Where:** `brain.py:1178–1179` (Paperclip activity log dropped), `routes.py:1013, 3296` (called into brain). Plus `brain.py:257–258` (try/except around setting `_last_consolidation` swallows everything — that file is in `memory/store.py:255–258`).
**What:** Cost events and audit trails go to /dev/null on transient failure with no metric, no retry, no replay queue.
**Fix:** Replace each with `except Exception as e: log.warning(...)` at minimum; ideally enqueue for retry.

### MEDIUM — `run_prediction` fabricates a fake signal
**Where:** `brain.py:1045–1061`.
**What:** Hand-builds one `InsightSignal` with placeholder content `f"Memory signal about {topic}"` rather than passing in actual signals from memory or Awarebot. The TODO is implicit (comment "simplified — would use actual signals from Awarebot in production"). This makes prediction confidence numbers meaningless.
**Fix:** Take signals as a parameter, default to `await self.scanner.scan_x(topic)` results.

### MEDIUM — `run_awarebot_scan` drops Reddit and signal scores
**Where:** `brain.py:979–1024`.
**What:** Initializes `results["sources"]["reddit"] = []` but never populates it — `scan_reddit` exists in `Scanner` (`scanner.py:252`) but is never called. Also truncates `s.content[:100]` and discards `relevance/novelty/actionability/source_authority/time_sensitivity`, breaking downstream scoring.
**Fix:** Add the reddit scan loop; pass the full signal dict (or a canonical projection) instead of the lossy 100-char preview.

### MEDIUM — Duplication that will drift between `brain.py` and `council.py`
- Pillar-keyword routing logic is in `brain.py:651–656` (text → PillarType) and the council also generates "PILLAR: NCC" strings — extraction lives in `brain._extract_mandates_from_council`. Both must stay in lockstep.
- `os.getenv("PAPERCLIP_URL", "http://localhost:3100")` appears 6+ times across the two files (brain.py:164, council.py:1005/1043/1083/1138/1182) and once in routes.
- `os.getenv("PAPERCLIP_COMPANY_ID", "")` appears 5+ times.
- Datetime + ISO formatting boilerplate `datetime.now(timezone.utc).isoformat()` appears 25+ times across both files.

**Fix:** Single helper module (`paperclip_adapter/config.py` or `_pcfg()` in client.py) returning a `(url, company_id)` tuple. One `now_iso()` helper.

### MEDIUM — `_dispatch_to_ncc` posts mandates with possibly-empty `mandate_id`
**Where:** `brain.py:711`.
**What:** `"mandate_id": m.get("mandate_id", "")`. If the mandate dict was the error-fallback shape (line 308 — `{"error": ..., "title": ...}`), the `if "error" in m: continue` at 682 saves us. But if `create_mandate` succeeded and the dict shape is correct, `mandate_id` is always present — the `, ""` default is dead. Worse, a downstream NCC accepting blank IDs would silently break correlation.
**Fix:** `m["mandate_id"]` and let it KeyError loudly. Remove the empty-string default.

### MEDIUM — `_extract_mandates_from_council` priority parsing is fragile
**Where:** `brain.py:631–646`.
**What:** Regex `re.search(r'(?:PRIORITY|...)\s*:\s*(\d+)', block)` will match "PRIORITY: 100" and clamp to 10, but won't match "Priority Level: P0" — which is the format brain itself uses to re-encode priority for NCC dispatch (line 702–708, "P0/P1/P2/P3"). The two halves of the system disagree on priority encoding.
**Fix:** Pick one canonical encoding (numeric 1–10 or P0–P3) and convert at the boundaries only.

### LOW — Quorum threshold contradicts log message
**Where:** `council.py:359–364`, `council.py:424–429`.
**What:** Code: `if unavailable_count > 2:` (i.e., 3+ fail). Log: `"Minimum 4 required."` With 6 members, `unavailable_count > 2` means `functioning_count < 4`, so 3 unavailable → 3 functioning → halts. But Round 2 uses `len(debaters) - unavailable_count` where `len(debaters) == 5`, so 3 unavailable in round 2 means only 2 functioning yet the same `> 2` threshold fires — the "minimum 4" claim only holds in round 1.
**Fix:** Compute `min_functioning` from a constant; assert `functioning_count >= min_functioning` consistently.

### LOW — Unbounded `_pending_dispatches` and `council_sessions`
**Where:** `brain.py:119–121`. Approved/rejected pumps remove from `_pending_dispatches`, but `council_sessions` is never pruned. Long-running process leaks sessions.

### LOW — `health_check` reports `uptime_pct: 100.0` (hard-coded)
**Where:** `brain.py:1097`. Always 100. MATRIX MONITOR fed a literal — meaningless.

### LOW — `__init__` doc lists `copilot_api_key` in signature but not in docstring
**Where:** `brain.py:45` vs `brain.py:54–72`. Cosmetic.

### LOW — Imports inside methods (`import httpx; import os` inside `_set_budget_policies` and `_dispatch_to_ncc`, `from datetime import timedelta` inside `_dispatch_to_ncc`, `from .models import CouncilMember` inside `spawn_council_session`).
**Where:** `brain.py:161–162, 669–670, 686, 749`. Hides dependencies from static analysis; minor perf hit on hot paths.

### LOW — `try / except (json.JSONDecodeError, TypeError, KeyError)` will not catch `AttributeError` from `parsed.get` if Claude returns a list.
**Where:** `council.py:829`. (Mentioned above.)

### LOW — No TODO/FIXME/XXX markers found in any of the three files. Comments at `brain.py:1044` ("simplified — would use actual signals from Awarebot in production") is the closest — implicit TODO.

---

## 4. Wiring Discrepancies

| # | Caller → Callee | Issue |
|---|-----------------|-------|
| 1 | `routes.py:3185, 3295` → `brain.process_pump(pump)` | Method doesn't exist. Should be `receive_pump_prompt`. **Critical.** |
| 2 | `routes.py:1003` → `brain.memory_store.query(days_back=1, limit=5)` | Method doesn't exist; should be `search_units(days_back=1)`. **Critical** (silently swallowed). |
| 3 | `routes.py:997` → `brain.memory_store.memory_units` | Attribute doesn't exist on `MemoryStore` (it's a file-backed store). The `hasattr` check makes it benign — total_units always reports 0. |
| 4 | `routes.py:375, 401` → `brain._pending_dispatches` | Routes reach into a private dict; should be a `list_pending()` / `get_pending(pump_id)` accessor on `NCLBrain`. |
| 5 | `routes.py:1201, 1206, 1430, 1444, 1535, 1551` → `brain._log_event` | Same private-method leak. Six call sites depend on the private signature. |
| 6 | `council.py:372, 437` → `ConsensusScore(confidence=..., reason=...)` | Pydantic model has neither field. **Critical.** |
| 7 | `brain.py:836–845` → `paperclip.create_mandate_as_issue(...)` | Signature matches `paperclip_adapter/client.py:175`. OK. |
| 8 | `brain.py:131–136` → `paperclip.register_company()` / `register_agent(name, description, role)` | Signatures match. OK. |
| 9 | `brain.py:1063` → `predictor.predict(signals, topic)` | Signature matches `awarebot/predictor.py:61`. OK. |
| 10 | `brain.py:996, 1010` → `scanner.scan_x(query, max_results=5)` / `scan_youtube(query, max_results=3)` | Signatures match (`scanner.py:143, 196`). OK. Note: `scan_reddit` exists but is never called. |
| 11 | `brain.py:1110–1113` → `predictor.close()` / `scanner.close()` / `paperclip.close()` / `council_engine.close()` | All four exist. OK. |
| 12 | `brain.py:1102` → `memory_store.get_stats()` | Exists (`memory/store.py:443`). Returns `{"total_units": ...}`. OK. |
| 13 | Brain → governance/* | **No imports.** The governance package (`PolicyKernel`, `ActionRouter`, `EmergencyStop`) is wired into routes.py:39–41 but never consulted by brain. Council decisions, mandate dispatch, and pump approval bypass the policy kernel entirely. This is the largest architectural gap — strategic-thinking core has no policy gate. |
| 14 | `routes.py:537` → `brain.spawn_council_session(topic, prompt, members)` | `members` arrives as `list[str] | None`; brain handles conversion. OK. But invalid member names are warned and dropped (brain.py:759), which can silently shrink to <quorum. |
| 15 | `routes.py:621` → `brain.create_mandate(...)` | Doesn't pass `status`, so default `MandateStatus.ACTIVE` is used. That bypasses the PENDING_APPROVAL gate when mandates are created via `POST /mandates` (no NATRIX review). **Worth flagging** — direct mandate creation skirts the human-in-the-loop. |

---

## 5. Quick Wins (impact / effort)

1. **Fix `process_pump` → `receive_pump_prompt`** in `routes.py:3185, 3295`. Two-line edit; restores intelligence-engine escalation pipeline. **(Critical / trivial.)**
2. **Add `confidence` and `reason` fields to `ConsensusScore`** (or stop passing them in `council.py:372, 437`). Five-line edit; quorum failures currently raise `ValidationError` in production. **(Critical / trivial.)**
3. **Fix `memory_store.query` → `search_units`** in `routes.py:1003`, drop the bare `except`. Restores dashboard "recent memory" panel. **(High / trivial.)**
4. **Replace `mandate.status = X` with `mandate.transition_to(X, reason=...)`** at `brain.py:395, 449, 902`. Activates the state machine + audit trail you already wrote. Wrap in try/except for now to avoid breaking COMPLETE→COMPLETE no-ops. **(High / 30 min.)**
5. **Add an `asyncio.Lock` and tmpfile-rename to `_persist_mandates`** (`brain.py:1194`). Closes the corruption window. Same lock can guard `_pending_dispatches` mutations. **(High / 1 hr.)**

Honourable mention: tighten the quorum string match in `council.py:353–356` and `418–421` — it's three lines and removes a class of false-positive halts.
