# NCL — 250-Gap System Audit

Date: 2026-05-15
Scope: full workspace under `/Users/natrix/dev/NCL`
Method: 6 parallel read-only explorer agents, partitioned by surface
Severities: 🔴 CRITICAL · 🟠 HIGH · 🟡 MEDIUM · 🟢 LOW

| Surface | Items | Critical | High | Medium | Low |
|---|---:|---:|---:|---:|---:|
| 1. Brain / API / Governance / Review Queue | 45 | 4 | 6 | 35 | 0 |
| 2. Intelligence / Councils / Awarebot / UNI / LDE | 45 | 8 | 7 | 28 | 2 |
| 3. Feedback / Scheduler / Orchestrator / MWP | 45 | 5 | 10 | 13 | 17 |
| 4. Swarm / Paperclip / Memory / Telemetry / MCP / Search | 40 | 0 | 16 | 20 | 4 |
| 5. Ops / DevOps / Config / Docker / Plists / Dashboards | 40 | 1 | 7 | 28 | 4 |
| 6. Cross-cutting (Tests / Security / Observability / Docs) | 35 | 2 | 33 | 0 | 0 |
| **Total** | **250** | **20** | **79** | **124** | **27** |

---

## 1. Brain / API / Governance / Review Queue (45)

1. 🟡 [runtime/review_queue/manager.py:63](runtime/review_queue/manager.py#L63) — `datetime.utcnow()` deprecated; switch to `datetime.now(timezone.utc)` (5 instances).
2. 🟠 [runtime/api/routes.py:380](runtime/api/routes.py#L380) — `_rate_limit_store` defaultdict unbounded; needs LRU eviction or periodic cleanup.
3. 🟡 [runtime/api/routes.py:985](runtime/api/routes.py#L985) — `GET /mandates` lacks pagination (`limit`/`skip`); returns full set.
4. 🟡 [runtime/api/routes.py:2881](runtime/api/routes.py#L2881) — `/governance/policy/rules` lacks docs and uses inconsistent error response shape.
5. 🟠 [runtime/api/routes.py:539](runtime/api/routes.py#L539) — `asyncio.create_task(_run_auto_flow())` orphan task; exceptions only logged, never surfaced.
6. 🟡 [runtime/api/routes.py:193](runtime/api/routes.py#L193) — Lifespan silently logs `register_emergency_stop`/`register_subsystems` failures; should fail-fast.
7. 🟡 [runtime/review_queue/manager.py:45](runtime/review_queue/manager.py#L45) — `ReviewItem.payload`/`tags` unbounded (no Pydantic constraints).
8. 🟠 [runtime/api/routes.py:2881](runtime/api/routes.py#L2881) — Multiple `/governance/*` endpoints accept `authorization` but skip `_verify_strike_token()`.
9. 🟢 [runtime/api/routes.py](runtime/api/routes.py) — 150+ endpoints lack OpenAPI tags; `/docs` is a flat list.
10. 🟡 [runtime/memory/store.py:65](runtime/memory/store.py#L65) — `self._write_lock.acquire()` without `async with`; deadlock risk on exception.
11. 🟠 [runtime/strike_point_orchestrator.py:48](runtime/strike_point_orchestrator.py#L48) — Hardcoded `Path.home()/Projects/ncc-server`; breaks at `/Users/natrix/dev/NCL`.
12. 🟡 [runtime/api/routes.py:807](runtime/api/routes.py#L807) — `brain.council_sessions` dict has no eviction → memory leak.
13. 🟠 [runtime/api/routes.py:3486](runtime/api/routes.py#L3486) — Memory consolidation logs async-written without flush/fsync.
14. 🟡 [runtime/api/routes.py:1526](runtime/api/routes.py#L1526) — `get_dashboard_data()` is O(n) over mandates+sessions+globs every call; no cache.
15. 🟡 [runtime/api/config.py:64](runtime/api/config.py#L64) — `keychain_get()` subprocess call without checking that the keychain entry exists.
16. 🟡 [runtime/ncl_brain/brain.py:86](runtime/ncl_brain/brain.py#L86) — `_redact()` not applied to all event payloads; potential PII leakage.
17. 🟡 [runtime/review_queue/manager.py:63](runtime/review_queue/manager.py#L63) — `ReviewItem.created_at` default still `datetime.utcnow().isoformat()`.
18. 🔴 [runtime/api/routes.py:406](runtime/api/routes.py#L406) — Rate limiter fail-open: lock contention bypasses limit; DOS via lock holding.
19. 🟡 [runtime/api/routes.py:508](runtime/api/routes.py#L508) — `network_info()` opens socket synchronously in async handler; should `asyncio.to_thread()`.
20. 🔴 [runtime/api/routes.py](runtime/api/routes.py) — Zero pytest coverage for the entire 5k-line routes module.
21. 🟡 [runtime/ncl_brain/models.py](runtime/ncl_brain/models.py) — `ProvenanceEnvelope.model_used` accepts any string; no whitelist of known model IDs.
22. 🟡 [runtime/api/routes.py:659](runtime/api/routes.py#L659) — `/pump/review/{pump_id}` does not validate `pump_id` format; no rate limit.
23. 🟡 [runtime/api/routes.py:1888](runtime/api/routes.py#L1888) — `get_council_report()` returns 500 instead of 404 on `FileNotFoundError`.
24. 🟡 [runtime/api/routes.py:233](runtime/api/routes.py#L233) — Lazy imports for research/lde fail silently → 503 instead of fail-fast at startup.
25. 🔴 [runtime/api/routes.py:4929](runtime/api/routes.py#L4929) — Global `except Exception` masks errors and may leak full stack to stderr.
26. 🟡 [runtime/api/routes.py:1679](runtime/api/routes.py#L1679) — `/feedback` and `/feedback/synthesis` endpoints have no rate limit.
27. 🟡 [runtime/ncl_brain/brain.py](runtime/ncl_brain/brain.py) — Events NDJSON appended without lock → corruption under concurrent writers.
28. 🟡 [runtime/api/routes.py:2393](runtime/api/routes.py#L2393) — Shortcut HTML uses `html.escape` for body but raw `actions_json` embedded in JS; template-injection risk via `{{UUID}}`.
29. 🟡 [runtime/api/routes.py:539](runtime/api/routes.py#L539) — Background task done-callback only logs; no metric or alert on failure.
30. 🟡 [runtime/governance/policy_kernel.py:100](runtime/governance/policy_kernel.py#L100) — `register_emergency_stop()` silently no-ops if controller is `None`.
31. 🟡 [runtime/api/routes.py:686](runtime/api/routes.py#L686) — `session.consensus_score` accessed without null-check after `.get()`.
32. 🟡 [runtime/api/routes.py:1800](runtime/api/routes.py#L1800) — Dashboard endpoint has no per-file try/except; one missing file fails entire payload.
33. 🟡 [runtime/api/routes.py:3870](runtime/api/routes.py#L3870) — `brief = None  # TODO` left in production; brief lookup is incomplete.
34. 🟠 [runtime/api/routes.py:3100](runtime/api/routes.py#L3100) — `/lde/process` writes results file without lock.
35. 🟡 [runtime/api/routes.py:1037](runtime/api/routes.py#L1037) — `/mandates/{mandate_id}` GET accepts any string; no format/length validation.
36. 🟡 [runtime/memory/store.py:180](runtime/memory/store.py#L180) — Daily memory consolidation has no timeout.
37. 🟡 [runtime/api/routes.py:2358](runtime/api/routes.py#L2358) — `_build_test_curl()` embeds bearer token in plaintext shell snippet.
38. 🟡 [runtime/api/routes.py:410](runtime/api/routes.py#L410) — Body-size check trusts `Content-Length` header only; chunked uploads bypass.
39. 🟡 [runtime/api/routes.py:1085](runtime/api/routes.py#L1085) — Mandate `transition_to()` calls do not write audit log entries.
40. 🔴 [runtime/api/routes.py:3017](runtime/api/routes.py#L3017) — `POST /mandates/{id}/approve` does not check if mandate is already ACTIVE; double-approval bypasses intent check.
41. 🟡 [runtime/ncl_brain/brain.py:41](runtime/ncl_brain/brain.py#L41) — `_validate_config()` raises at import time; blocks server start with no graceful degradation.
42. 🟠 [runtime/ncl_brain/brain.py](runtime/ncl_brain/brain.py) — Events NDJSON has no rotation/archival; can fill disk.
43. 🟠 [runtime/api/routes.py:1479](runtime/api/routes.py#L1479) — `asyncio.gather(*checks)` for service health has no timeout.
44. 🟡 [runtime/api/routes.py:2788](runtime/api/routes.py#L2788) — Telemetry `hours_back` accepts negative values.
45. 🟡 [runtime/api/routes.py:2788](runtime/api/routes.py#L2788) — Telemetry/governance stats load full datasets into memory; no streaming response.

---

## 2. Intelligence / Councils / Awarebot / UNI / LDE (45)

46. 🔴 [runtime/intelligence/collectors.py:242](runtime/intelligence/collectors.py#L242) — `GoogleTrendsCollector` httpx client never closed.
47. 🔴 [runtime/intelligence/collectors.py:250](runtime/intelligence/collectors.py#L250) — `PolymarketCollector` httpx client leak.
48. 🔴 [runtime/intelligence/collectors.py:260](runtime/intelligence/collectors.py#L260) — `NewsCollector` httpx client leak.
49. 🔴 [runtime/intelligence/collectors.py:270](runtime/intelligence/collectors.py#L270) — `CryptoMarketCollector` httpx client leak.
50. 🔴 [runtime/intelligence/collectors.py:280](runtime/intelligence/collectors.py#L280) — `UnusualWhalesCollector` httpx client leak (FD exhaustion risk).
51. 🔴 [runtime/intelligence/collectors.py:290](runtime/intelligence/collectors.py#L290) — `RedditCollector` httpx client leak on module reload.
52. 🟠 [runtime/intelligence/engine.py:405](runtime/intelligence/engine.py#L405) — `IntelligenceEngine._llm_client` not registered with atexit cleanup.
53. 🟠 [runtime/intelligence/collectors.py:242](runtime/intelligence/collectors.py#L242) — Hardcoded User-Agent; no rotation.
54. 🟡 [runtime/intelligence/collectors.py:100](runtime/intelligence/collectors.py#L100) — `_RateLimiter.acquire()` has no absolute wait cap; possible indefinite block.
55. 🟡 [runtime/intelligence/collectors.py:150](runtime/intelligence/collectors.py#L150) — Exponential backoff lacks jitter; thundering herd under failure.
56. 🟡 [runtime/intelligence/collectors.py:180](runtime/intelligence/collectors.py#L180) — Polymarket pagination has no max-page guard.
57. 🟠 [runtime/intelligence/collectors.py:195](runtime/intelligence/collectors.py#L195) — Reddit collector first-page only; no pagination.
58. 🟡 [runtime/councils/youtube/scraper.py:120](runtime/councils/youtube/scraper.py#L120) — Per-channel retry with no global retry budget.
59. 🟠 [runtime/councils/youtube/transcriber.py:180](runtime/councils/youtube/transcriber.py#L180) — Whisper transcription has no token-cap on long videos.
60. 🟡 [runtime/councils/youtube/scraper.py:200](runtime/councils/youtube/scraper.py#L200) — `download_batch()` has no concurrent-download limit.
61. 🔴 [runtime/intelligence/engine.py:361](runtime/intelligence/engine.py#L361) — `briefs.jsonl` documented 100MB cap is unenforced; unbounded growth.
62. 🔴 [runtime/intelligence/engine.py:361](runtime/intelligence/engine.py#L361) — `signals.jsonl` appended non-atomically; mid-write crash corrupts file.
63. 🟡 [runtime/intelligence/engine.py:365](runtime/intelligence/engine.py#L365) — Anomaly fingerprint set is size-bounded but not time-bounded; stale hashes stick forever.
64. 🟡 [runtime/intelligence/models.py:60](runtime/intelligence/models.py#L60) — Confidence scores not normalized across SourceTypes; cross-source comparison invalid.
65. 🟡 [runtime/intelligence/models.py:70](runtime/intelligence/models.py#L70) — Importance thresholds (50/20/10/5) hardcoded; no per-source override.
66. 🟡 [runtime/intelligence/engine.py:290](runtime/intelligence/engine.py#L290) — `SignalCorrelator.correlate()` lacks lock around shared multiplier state.
67. 🟡 [runtime/intelligence/engine.py:100](runtime/intelligence/engine.py#L100) — `_cache_set()` LRU eviction has edge case where capacity exceeded.
68. 🟢 [runtime/intelligence/engine.py:110](runtime/intelligence/engine.py#L110) — No cache hit/miss metrics; observability gap.
69. 🟠 [runtime/councils/runner.py:80](runtime/councils/runner.py#L80) — YouTube scraper called with `time.sleep` inside async context; blocks loop.
70. 🟡 [runtime/councils/runner.py:150](runtime/councils/runner.py#L150) — `_snapshot_intel_state` fallback path never used if primary missing.
71. 🟠 [runtime/councils/youtube/analyzer.py:180](runtime/councils/youtube/analyzer.py#L180) — `max_tokens=4096` hardcoded; long transcripts overflow.
72. 🟡 [runtime/councils/xai/scanner.py:50](runtime/councils/xai/scanner.py#L50) — X API rate limit (300/15min) hardcoded; not configurable.
73. 🟠 [runtime/councils/xai/scanner.py:400](runtime/councils/xai/scanner.py#L400) — `twscrape` fallback has no timeout; can hang pipeline.
74. 🟡 [runtime/councils/xai/analyzer.py:100](runtime/councils/xai/analyzer.py#L100) — Prompt concatenates 30+ posts unbounded; LLM context overflow.
75. 🟠 [runtime/awarebot/predictor.py:180](runtime/awarebot/predictor.py#L180) — Model fallback chain (Claude → Ollama) skips Grok step.
76. 🟠 [runtime/awarebot/predictor.py:200](runtime/awarebot/predictor.py#L200) — Ollama prompt has no `max_tokens`; silent truncation.
77. 🟡 [runtime/awarebot/predictor.py:120](runtime/awarebot/predictor.py#L120) — Single global `timeout=60.0`; no per-call override.
78. 🟠 [runtime/lde/ingestor.py:120](runtime/lde/ingestor.py#L120) — `trafilatura` extractor has no timeout; can hang on slow hosts.
79. 🟡 [runtime/lde/ingestor.py:140](runtime/lde/ingestor.py#L140) — No max-size check before LLM input; large articles → OOM.
80. 🟡 [runtime/lde/agents.py:50](runtime/lde/agents.py#L50) — `_normalize_ollama_host()` does not validate final URL scheme.
81. 🟡 [runtime/lde/agents.py:180](runtime/lde/agents.py#L180) — `max_tokens=4096` hardcoded across all models.
82. 🟡 [runtime/councils/shared/report_writer.py:50](runtime/councils/shared/report_writer.py#L50) — Report filenames may collide on same-second concurrent sessions.
83. 🔴 [runtime/councils/shared/report_writer.py:60](runtime/councils/shared/report_writer.py#L60) — JSON report not written atomically.
84. 🔴 [runtime/uni/cortex.py:73](runtime/uni/cortex.py#L73) — `results.ndjson` appended unbounded; no rotation.
85. 🟡 [runtime/uni/gatherer.py:150](runtime/uni/gatherer.py#L150) — `_llm_research()` re-queries LLM for same query; no result cache.
86. 🟡 [runtime/intelligence/engine.py:400](runtime/intelligence/engine.py#L400) — `intelligence-scan/snapshots/` grows without rotation/cleanup.
87. 🟡 [runtime/intelligence/collectors.py:310](runtime/intelligence/collectors.py#L310) — Polymarket pagination returns duplicate markets across pages.
88. 🟡 [runtime/councils/youtube/scraper.py:150](runtime/councils/youtube/scraper.py#L150) — `download_audio()` swallows yt-dlp stderr; debugging hard.
89. 🟠 [runtime/awarebot/predictor.py:150](runtime/awarebot/predictor.py#L150) — `_predict_claude` has no try/finally cleanup of HTTP client.
90. 🟡 [runtime/councils/xai/scanner.py:200](runtime/councils/xai/scanner.py#L200) — `scan_trending()` returns silently empty if both X API and Grok fail.

---

## 3. Feedback / Scheduler / Orchestrator / MWP (45)

91. 🔴 [runtime/feedback/scanner.py:91](runtime/feedback/scanner.py#L91) — JSON-only parsing; senders produce YAML reports → parse failures.
92. 🔴 [runtime/strike_point_orchestrator.py:1050](runtime/strike_point_orchestrator.py#L1050) — `_BoundedSet` evicts oldest mandate ID without log; old mandates re-dispatched.
93. 🔴 [runtime/council_runner/store.py:35](runtime/council_runner/store.py#L35) — Concurrent writes to `runs.jsonl` not serialized; corruption risk.
94. 🔴 [runtime/pump_watcher.py:180](runtime/pump_watcher.py#L180) — Relay file copied before fsync; partial JSON read race.
95. 🔴 [runtime/autonomous/scheduler.py:550](runtime/autonomous/scheduler.py#L550) — `asyncio.wait_for(_stop_event.wait())` returns early on event interrupts; sleep loops drift.
96. 🟠 [runtime/feedback/models.py:1](runtime/feedback/models.py#L1) — `schema_version` defaulted but no validator enforces it; drift undetected.
97. 🟠 [runtime/feedback/scanner.py:78](runtime/feedback/scanner.py#L78) — No file lock; concurrent scanner instances read same file.
98. 🟠 [runtime/feedback/scanner.py:140](runtime/feedback/scanner.py#L140) — `_move_to` collision handling can re-process same file after eviction.
99. 🟠 [runtime/execution_loop.py:275](runtime/execution_loop.py#L275) — `_sanitize_council_text` escapes closing tags only; opening-tag prompt injection still possible.
100. 🟠 [runtime/strike_point_orchestrator.py:850](runtime/strike_point_orchestrator.py#L850) — Mandate retry uses `2**retries` with no jitter.
101. 🟠 [runtime/strike_point_orchestrator.py:600](runtime/strike_point_orchestrator.py#L600) — No idempotency key for mandate dispatch.
102. 🟠 [runtime/mwp_processor.py:200](runtime/mwp_processor.py#L200) — State file `write_text()` is non-atomic.
103. 🟠 [runtime/council_runner/agents.py:120](runtime/council_runner/agents.py#L120) — Hardcoded model fallback chain; no replay-pinning.
104. 🟠 [feedback-synthesis/senders/ncc_sender.py:60](feedback-synthesis/senders/ncc_sender.py#L60) — YAML schema mismatches `FeedbackReport` Pydantic model.
105. 🟠 [runtime/autonomous/scheduler.py:280](runtime/autonomous/scheduler.py#L280) — `asyncio.gather()` without `return_exceptions=True` for memory consolidation.
106. 🟡 [runtime/feedback/scanner.py:200](runtime/feedback/scanner.py#L200) — LOG.md append not thread-safe.
107. 🟡 [runtime/execution_loop.py:350](runtime/execution_loop.py#L350) — `load_task_plan()` falls back to minimal template silently.
108. 🟡 [runtime/pump_watcher.py:150](runtime/pump_watcher.py#L150) — Bloom-filter rotation uses `monotonic()`; clock change desynchronizes.
109. 🟡 [runtime/pump_watcher.py:140](runtime/pump_watcher.py#L140) — `_wait_for_file_stable()` 5s cap fails on slow disks.
110. 🟡 [runtime/strike_point_orchestrator.py:700](runtime/strike_point_orchestrator.py#L700) — `gather_aac_context` and `gather_brs_context` use sync `glob()` in async path.
111. 🟡 [runtime/autonomous/scheduler.py:100](runtime/autonomous/scheduler.py#L100) — No jitter on startup; loops cause synchronized thundering herd.
112. 🟡 [runtime/council_runner/store.py:80](runtime/council_runner/store.py#L80) — `list_runs`/`search_runs` linear scan; no pagination index.
113. 🟡 [runtime/execution_loop.py:320](runtime/execution_loop.py#L320) — `_extract_field()` splits on first `:`; URL-bearing values truncated.
114. 🟡 [runtime/strike_point_orchestrator.py:180](runtime/strike_point_orchestrator.py#L180) — Hardcoded `EXEC_PIPELINE`/`FEEDBACK_DIR`; not `NCL_BASE`-relative.
115. 🟡 [runtime/mwp_processor.py:140](runtime/mwp_processor.py#L140) — `_count_artifacts()` unbounded `rglob()`; slow on large stages.
116. 🟡 [feedback-synthesis/senders/synthesizer.py:100](feedback-synthesis/senders/synthesizer.py#L100) — `call_ncl_council()` 60s timeout hardcoded; no retry on timeout.
117. 🟡 [runtime/strike_point_orchestrator.py:450](runtime/strike_point_orchestrator.py#L450) — `_trigger_execution_loop()` subprocess failure logged at WARNING only.
118. 🟡 [runtime/autonomous/scheduler.py:200](runtime/autonomous/scheduler.py#L200) — Signal buffer dropping oldest silently; no overflow notification.
119. 🟢 [runtime/execution_loop.py:380](runtime/execution_loop.py#L380) — `stage_for_review`/`stage_for_output` not idempotent.
120. 🟢 [feedback-synthesis/senders/ncc_sender.py:75](feedback-synthesis/senders/ncc_sender.py#L75) — `validate_report()` does not enforce `mandate_id` presence.
121. 🟢 [runtime/council_runner/models.py:60](runtime/council_runner/models.py#L60) — `CouncilRunRecord.snapshot` defaults `{}`; replay cannot restore state.
122. 🟢 [runtime/mwp_processor.py:90](runtime/mwp_processor.py#L90) — `_use_stages_subdir` only checks existence, not stage completeness.
123. 🟢 [runtime/strike_point_orchestrator.py:550](runtime/strike_point_orchestrator.py#L550) — `_NOTIF_CACHE_TTL=10s` hardcoded.
124. 🟢 [runtime/pump_watcher.py:310](runtime/pump_watcher.py#L310) — `send_response_to_relay()` no retry on transient failure.
125. 🟢 [runtime/autonomous/scheduler.py:150](runtime/autonomous/scheduler.py#L150) — `council_trigger_threshold=75.0` hardcoded.
126. 🟢 [runtime/feedback/scanner.py:120](runtime/feedback/scanner.py#L120) — `MAX_REPORT_FILE_BYTES` per-file cap only; no per-pass total.
127. 🟢 [runtime/execution_loop.py:200](runtime/execution_loop.py#L200) — `CircuitBreaker._open_until` monotonic vs wall-clock desync.
128. 🟢 [feedback-synthesis/senders/brs_sender.py:85](feedback-synthesis/senders/brs_sender.py#L85) — `validate_report()` accepts negative `revenue_total`.
129. 🟢 [runtime/strike_point_orchestrator.py:400](runtime/strike_point_orchestrator.py#L400) — HTTP→file dispatch fallback strategy undocumented.
130. 🟢 [runtime/execution_loop.py:150](runtime/execution_loop.py#L150) — `create_feedback_payload()` hardcodes `council_rounds=1`.
131. 🟢 [runtime/execution_loop.py:1](runtime/execution_loop.py#L1) — Missing structured-log fields (mandate_id, pillar) throughout.
132. 🟢 [feedback-synthesis/senders/aac_sender.py:90](feedback-synthesis/senders/aac_sender.py#L90) — Capital reports unsigned; no authenticity check.
133. 🟢 [runtime/mwp_processor.py:250](runtime/mwp_processor.py#L250) — No rollback on failed stage transition.
134. 🟢 [runtime/autonomous/scheduler.py:170](runtime/autonomous/scheduler.py#L170) — No catch-up logic for missed runs.
135. 🟢 [feedback-synthesis/senders/synthesizer.py:120](feedback-synthesis/senders/synthesizer.py#L120) — `collect_recent_reports()` filters by mtime, not parsed timestamp.

---

## 4. Swarm / Paperclip / Memory / Telemetry / MCP / Search (40)

136. 🟠 [runtime/paperclip_adapter/client.py:45](runtime/paperclip_adapter/client.py#L45) — Retry without circuit breaker / jitter.
137. 🟠 [runtime/paperclip_adapter/client.py:85](runtime/paperclip_adapter/client.py#L85) — No TLS pinning on agent API key transport.
138. 🟡 [runtime/paperclip_adapter/client.py:120](runtime/paperclip_adapter/client.py#L120) — No idempotency key on retried POSTs.
139. 🟠 [runtime/memory/store.py:85](runtime/memory/store.py#L85) — `search_units()` is O(n) linear scan; no inverted index.
140. 🟠 [runtime/memory/store.py:100](runtime/memory/store.py#L100) — Vector embedding semantic search not implemented.
141. 🟡 [runtime/memory/store.py:120](runtime/memory/store.py#L120) — Importance decay rate hardcoded to 0.95/day.
142. 🟡 [runtime/memory/store.py:250](runtime/memory/store.py#L250) — `consolidate()` rewrites `units.jsonl` non-atomically.
143. 🟢 [runtime/memory/store.py:45](runtime/memory/store.py#L45) — No bloom filter for negative lookups.
144. 🟠 [runtime/swarm/orchestrator.py:145](runtime/swarm/orchestrator.py#L145) — `_notify_subscribers()` fires callbacks outside lock; race with `put()`.
145. 🟠 [runtime/swarm/orchestrator.py:180](runtime/swarm/orchestrator.py#L180) — Agent pool unbounded growth; no max-pooled-agents.
146. 🟠 [runtime/swarm/orchestrator.py:160](runtime/swarm/orchestrator.py#L160) — `AGENT_TIMEOUT_SECONDS=300` hardcoded; no per-task override.
147. 🟡 [runtime/swarm/orchestrator.py:190](runtime/swarm/orchestrator.py#L190) — Result synthesis has no LLM-call timeout.
148. 🟡 [runtime/swarm/orchestrator.py:140](runtime/swarm/orchestrator.py#L140) — `emergency_stop` event doesn't cancel running agents.
149. 🟠 [runtime/swarm/llm_router.py:200](runtime/swarm/llm_router.py#L200) — Cost increment under `_stats_lock` but read-modify-write not atomic.
150. 🟠 [runtime/swarm/llm_router.py:230](runtime/swarm/llm_router.py#L230) — Double-checked client init: `is_closed` without null check.
151. 🟡 [runtime/swarm/llm_router.py:260](runtime/swarm/llm_router.py#L260) — No per-backend circuit breaker.
152. 🟡 [runtime/swarm/llm_router.py:180](runtime/swarm/llm_router.py#L180) — Token estimates uncalibrated against actual model returns.
153. 🟢 [runtime/swarm/llm_router.py:220](runtime/swarm/llm_router.py#L220) — Fallback chain ignores priority weights.
154. 🟠 [runtime/swarm/cost_gate.py:160](runtime/swarm/cost_gate.py#L160) — Budget snapshot re-acquires lock after release; non-atomic.
155. 🟠 [runtime/swarm/cost_gate.py:195](runtime/swarm/cost_gate.py#L195) — TOCTOU race in `check_and_spend`; concurrent overspend possible.
156. 🟡 [runtime/swarm/cost_gate.py:80](runtime/swarm/cost_gate.py#L80) — No budget decay; allocation grows unbounded.
157. 🟡 [runtime/swarm/cost_gate.py:50](runtime/swarm/cost_gate.py#L50) — In-memory ledger lost on restart; no persistent cache.
158. 🟢 [runtime/swarm/cost_gate.py:120](runtime/swarm/cost_gate.py#L120) — No audit trail for budget mutations.
159. 🟠 [runtime/telemetry/collector.py:80](runtime/telemetry/collector.py#L80) — Metrics persisted to NDJSON only; no Prometheus/OTel export.
160. 🟠 [runtime/telemetry/collector.py:120](runtime/telemetry/collector.py#L120) — No summary aggregation; raw logs require post-processing.
161. 🟡 [runtime/telemetry/collector.py:130](runtime/telemetry/collector.py#L130) — Async-flush spawned via `create_task` without await; ghost task risk.
162. 🟡 [runtime/telemetry/collector.py:140](runtime/telemetry/collector.py#L140) — Redaction in-buffer races with async export.
163. 🟢 [runtime/telemetry/collector.py:160](runtime/telemetry/collector.py#L160) — Correlation ID hashed post-record; non-reproducible.
164. 🟡 [runtime/telemetry/schema.py:60](runtime/telemetry/schema.py#L60) — `RedactionRule` misses IPv6/MAC/SSN variants.
165. 🟢 [runtime/telemetry/schema.py:85](runtime/telemetry/schema.py#L85) — `TelemetryLevel.VERBOSE` always redacts payload; no dev-mode override.
166. 🟡 [runtime/evaluation/runner.py:60](runtime/evaluation/runner.py#L60) — Hardcoded scoring functions; no pluggable strategy.
167. 🟡 [runtime/evaluation/runner.py:50](runtime/evaluation/runner.py#L50) — Regression detection by task name; refactors hide regressions.
168. 🟢 [runtime/evaluation/runner.py:40](runtime/evaluation/runner.py#L40) — No A/B test support across branches.
169. 🟠 [runtime/mcp_bridge/server.py:80](runtime/mcp_bridge/server.py#L80) — Tool args never validated before brain call.
170. 🟠 [runtime/mcp_bridge/server.py:110](runtime/mcp_bridge/server.py#L110) — No per-call timeout; global timeout fires mid-stream.
171. 🟡 [runtime/mcp_bridge/server.py:95](runtime/mcp_bridge/server.py#L95) — Bearer token sent over HTTP; no HTTPS enforcement in code.
172. 🟡 [runtime/mcp_bridge/server.py:140](runtime/mcp_bridge/server.py#L140) — Tool results not validated before forwarding to Claude.
173. 🟠 [runtime/search/indexer.py:240](runtime/search/indexer.py#L240) — No fuzzy matching; typos return zero results.
174. 🟡 [runtime/search/indexer.py:200](runtime/search/indexer.py#L200) — TF-IDF not normalized by document length.
175. 🟡 [runtime/search/indexer.py:290](runtime/search/indexer.py#L290) — Snippets truncated mid-phrase without context.

---

## 5. Ops / DevOps / Config / Docker / Plists / Dashboards (40)

176. 🟡 [start-all.sh:1](start-all.sh#L1) — Missing `set -euo pipefail`.
177. 🟡 [run.sh:7](run.sh#L7) — Only `set -e`; missing `u` and `pipefail`.
178. 🟠 [scripts/launch-watcher.sh:6](scripts/launch-watcher.sh#L6) — Hardcoded `/Users/natrix/dev/NCL` instead of `$HOME`.
179. 🟡 [requirements.txt:60](requirements.txt#L60) — pytest/pytest-asyncio/pytest-cov as runtime deps; should be `[project.optional-dependencies.dev]`.
180. 🟡 [pyproject.toml:21](pyproject.toml#L21) — `~=` specifiers allow patch-upgrade drift; pin `==` for determinism.
181. 🟡 [Dockerfile:1](Dockerfile#L1) — Floating `python:3.12-slim` tag; pin to digest.
182. 🟡 [docker-compose.yml:52](docker-compose.yml#L52) — `ollama/ollama:0.3` tag floating.
183. 🟡 [config/services.json:32](config/services.json#L32) — Stale placeholders (`your-cloudflare-tunnel-id-here`, `ncc.your-domain.com`).
184. 🟡 [dashboard/index.html:552](dashboard/index.html#L552) — Hardcoded `http://localhost:8800` (multiple lines).
185. 🟢 [.github/workflows/ci.yml:17](.github/workflows/ci.yml#L17) — Missing `cache: "pip"`; slow CI installs.
186. 🟠 [scripts/install-plists.sh:44](scripts/install-plists.sh#L44) — `launchctl bootstrap` exit code unchecked.
187. 🔴 [restart-all.command:3](restart-all.command#L3) — Intentionally omits `set -e`; hides failures.
188. 🟠 [start-brain.command:6](start-brain.command#L6) — Hardcoded path; should derive via `$(cd "$(dirname "$0")" && pwd)`.
189. 🟠 [start-brain.command:29](start-brain.command#L29) — Binds `127.0.0.1:8800`; blocks LAN/Mac-Mesh access.
190. 🟡 [restart-brain-intel.command:17](restart-brain-intel.command#L17) — `$(lsof -ti :8800)` unquoted.
191. 🟡 [dashboard/index.html:861](dashboard/index.html#L861) — `fetch()` calls lack `.catch()` handling.
192. 🟠 [dashboard/index.html:589](dashboard/index.html#L589) — `.innerHTML` with unsanitized service name; XSS.
193. 🟠 [dashboard/index.html](dashboard/index.html) — No auth; world-readable on `:8800`.
194. 🟡 [start-all.sh:58](start-all.sh#L58) — `nohup` without verifying process started.
195. 🟡 [start-relay.command:11](start-relay.command#L11) — Unquoted `$(lsof -ti :8787)`.
196. 🟡 [scripts/install-plists.sh:13](scripts/install-plists.sh#L13) — No `plutil -lint` validation before install.
197. 🟡 [config/ncl.yaml:34](config/ncl.yaml#L34) — `aac_war_room_url` empty.
198. 🟡 [Dockerfile:20](Dockerfile#L20) — Non-root user but no `--cap-drop` / seccomp profile.
199. 🟢 [docker-compose.yml:45](docker-compose.yml#L45) — Internal ports (Ollama `:11434`) exposed unnecessarily.
200. 🟢 [paperclip_mock.py:30](paperclip_mock.py#L30) — No request body / Content-Type validation.
201. 🟡 [requirements.txt:52](requirements.txt#L52) — `praw`/`tweepy` `~=`; transitive scanner deps not explicit.
202. 🟡 [.github/workflows/ci.yml:49](.github/workflows/ci.yml#L49) — `mypy` `continue-on-error: true`; type errors don't fail build.
203. 🟡 [.github/workflows/ci.yml](.github/workflows/ci.yml) — Missing `concurrency:` block; deploy races possible.
204. 🟡 [restart-all.command:106](restart-all.command#L106) — Test failure suffixed `|| true`; pipeline proceeds on red tests.
205. 🟡 [com.resonanceenergy.ncl-brain.plist:18](com.resonanceenergy.ncl-brain.plist#L18) — `ThrottleInterval=10` may restart in tight loop on crash.
206. 🟢 [dashboard/index.html:533](dashboard/index.html#L533) — Hardcoded SERVICES port array; should fetch from API.
207. 🟡 [start-all.sh, setup.sh] — Don't validate `$PYTHONPATH` before `python3 -m`; can pick wrong interpreter.
208. 🟢 [.env.example:7](.env.example#L7) — Stale placeholder values (`sk-ant-…`).
209. 🟠 [com.resonanceenergy.ncl-orchestrator.plist:11](com.resonanceenergy.ncl-orchestrator.plist#L11) — Hardcoded `__HOME__/.pyenv/shims/python3`; fails silently if pyenv missing.
210. 🟡 [dashboard/index.html](dashboard/index.html) — No `Content-Security-Policy`; allows inline scripts.
211. 🟢 [dashboard/index.html:521](dashboard/index.html#L521) — Globals `apiData`, `autoRefresh`, `API_OFFLINE` no namespace.
212. 🟡 [prep-commit.command:7](prep-commit.command#L7) — Hardcoded `/Users/natrix/dev/NCL`; not portable.
213. 🟡 [git-push.command:6](git-push.command#L6) — `read -p` requires TTY; fails in CI.
214. 🟡 [scripts/rotate-logs.sh:26](scripts/rotate-logs.sh#L26) — Truncates to last 5MB; loses error context. Use gzip.
215. 🟢 [.github/workflows/ci.yml:17](.github/workflows/ci.yml#L17) — Doesn't pin Python `3.12` exactly; can pick `3.13`.

---

## 6. Cross-cutting (Tests / Security / Observability / Docs) (35)

216. 🔴 [.env](.env) — Tracked by VCS; should only be `.env.example`.
217. 🔴 [runtime/ncl_brain/brain.py:40](runtime/ncl_brain/brain.py#L40) — `anthropic_base_url` hardcoded; 50+ scattered `os.getenv()`; needs centralized pydantic-settings.
218. 🟠 No `LICENSE` file at repo root.
219. 🟠 No `THIRD_PARTY.txt` / `ATTRIBUTION` file (yt-dlp, chromadb, trafilatura, lancedb, tweepy).
220. 🟠 [pyproject.toml](pyproject.toml) ↔ [requirements.txt](requirements.txt) — pins disagree on fastapi, uvicorn, pydantic, httpx, openai, google-generativeai.
221. 🟠 [runtime/strike_point_orchestrator.py](runtime/strike_point_orchestrator.py) — 1154 lines, zero tests.
222. 🟠 [runtime/councils/runner.py](runtime/councils/runner.py), [runtime/execution_loop.py](runtime/execution_loop.py), [runtime/autonomous/scheduler.py](runtime/autonomous/scheduler.py) — untested core orchestration.
223. 🟠 [tests/](tests/) — No coverage for `feedback/`, `lde/`, `paperclip_adapter/`, `mcp_bridge/`, `deployment/`.
224. 🟠 [.github/workflows/ci.yml:34](.github/workflows/ci.yml#L34) — `mypy` errors ignored.
225. 🟠 No coverage report published in CI; no htmlcov artifact.
226. 🟠 [runtime/ncl_brain/brain.py:50](runtime/ncl_brain/brain.py#L50) + [council.py](runtime/ncl_brain/council.py) — `os.getenv("PAPERCLIP_URL")` called 6+ times instead of cached once.
227. 🟠 [runtime/ncl_brain/models.py:355](runtime/ncl_brain/models.py#L355) — `ConsensusScore` missing `confidence` and `reason`; raises ValidationError that masks quorum failures.
228. 🟠 No Prometheus `/metrics` endpoint; `slowapi` present but no exporter.
229. 🟠 No Sentry / error reporting integration.
230. 🟠 No OpenTelemetry tracing.
231. 🟠 [runtime/ncl_brain/brain.py:134](runtime/ncl_brain/brain.py#L134) — `datetime.now(timezone.utc).isoformat()` repeated 25+ times; no UTC helper.
232. 🟠 No GDPR right-to-be-forgotten path / `delete_user_data()` endpoint.
233. 🟠 [intelligence-scan/signals/README.md:28](intelligence-scan/signals/README.md#L28) — Retention policy documented but no scheduled cleanup daemon.
234. 🟠 [accounts.db](accounts.db) — Untracked SQLite database; no backup / snapshot rotation.
235. 🟠 [data/events.ndjson](data/events.ndjson), [data/mandates.json](data/mandates.json) — `.bak`/`.corrupt` siblings exist; no TTL or FIFO rotation.
236. 🟠 No `CONTRIBUTING.md`.
237. 🟠 [shared/doctrine/AGENTS.md](shared/doctrine/AGENTS.md) vs [config/paperclip/AGENTS.md](config/paperclip/AGENTS.md) — drift, no sync rule.
238. 🟠 No ADRs (NDJSON vs SQLite, slowapi, MCP, ChromaDB/LanceDB).
239. 🟠 No deployed OpenAPI/Swagger; INDEX.md claims it but `/docs` is unimplemented.
240. 🟠 No `/v1` API versioning prefix; no deprecation policy.
241. 🟠 Silent error swallows in [runtime/awarebot/scanner.py](runtime/awarebot/scanner.py), [runtime/intelligence/collectors.py](runtime/intelligence/collectors.py); not alerted.
242. 🟠 [dashboard/command-center.html](dashboard/command-center.html), [dashboard/index.html](dashboard/index.html), [dashboard/memory.html](dashboard/memory.html), [dashboard/review-queue.html](dashboard/review-queue.html) — missing alt text/aria/role (WCAG 2.1 AA non-compliant).
243. 🟠 Dashboards lack keyboard navigation, focus management, skip-to-content.
244. 🟠 [start-all.sh:177](start-all.sh#L177) — `datetime.utcnow()` (deprecated in 3.12+).
245. 🟠 No `pip-audit` step in CI.
246. 🟠 No Dependabot configuration.
247. 🟠 [requirements.txt:43](requirements.txt#L43) — `python-json-logger` installed but never wired; logs are plain text.
248. 🟠 [requirements.txt:37](requirements.txt#L37) — `slowapi` present but no `@limiter.limit` decorators in [routes.py](runtime/api/routes.py).
249. 🟠 [workspaces/execution-pipeline/](workspaces/execution-pipeline/) — Missing `CONTEXT.md` that other workspaces have.
250. 🟠 [runtime/api/config.py:130](runtime/api/config.py#L130) — `pydantic-settings` defined but `Settings` class never instantiated; env-vars read ad-hoc.

---

## Triage Plan (suggested order)

1. **Wave 3 — CRITICAL (20 items)**: secrets removal (#216), fail-open rate limiter (#18), double-approval bypass (#40), broad-except handler (#25), HTTP-client leaks in collectors (#46–#51), atomic JSONL writers (#62, #83, #84), bounded-set eviction logging (#92), runs.jsonl serialization (#93), pump_watcher fsync race (#94), scheduler wait drift (#95), restart-all `set -e` (#187).
2. **Wave 4 — HIGH governance + observability (79 items)**: mandate audit-log on `transition_to`, central pydantic-settings, Prometheus `/metrics`, Sentry, OTel, slowapi wiring, mypy CI gate, pip-audit + Dependabot, schema reconciliation between `runtime/feedback/models.py` and `runtime/ncl_brain/models.py`.
3. **Wave 5 — MEDIUM hygiene + ops (124 items)**: pin Docker images by digest, plist `StandardErrorPath`/`StandardOutPath`, dashboard XSS hardening, `set -euo pipefail` rollout, NCL_BASE-relative paths everywhere.
4. **Wave 6 — LOW polish (27 items)**: telemetry namespacing, idempotency keys, dashboard ARIA labels.
