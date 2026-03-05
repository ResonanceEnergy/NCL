# NCL NuraulCortexLink — 100-Step Market Roadmap

This roadmap is structured for AI-autonomous execution with clear mandates, exit criteria, and sequencing.


## 01. Strategy & Identity

**Mandate:** See per-step goals below.

01. Define product promise & one-liner; lock official name (NCL NuraulCortexLink).
02. Finalize target personas & top JTBD (mobile-first, researcher, operator).
03. Set North-Star metrics (T2N, Q&A P95, D7/D30, Local-only adoption).
04. Decide pricing tiers (Free/Pro/Sync add-on) and value fences.
05. Establish brand voice & taglines; draft landing page narrative.
06. Approve iconography/color/typography minimal set (dark-mode first).
07. Select legal structure & app store account ownership.
08. Define governance: privacy-first mandates; citations mandatory for AI.
09. Approve success SLOs and guardrails for performance and battery.
10. Publish Strategy Brief v1.0 to /docs/product.

## 02. Architecture & Privacy

**Mandate:** See per-step goals below.

11. Choose local-first data model (Markdown + SQLite/FTS + local vectors).
12. Specify provenance schema (source_app,url,timestamp,device_id,hash).
13. Design Local-only Mode default; explicit opt-in cloud AI/sync.
14. Define E2E Private Sync key management plan (per-device keys).
15. Draft Export/Deletion guarantees; human-readable archive spec.
16. Plan background indexer (incremental, battery-aware).
17. Establish Privacy HUD: local vs remote, redactions, sync state.
18. Map app intents/Shortcuts/Widgets integration surface.
19. Security review checklist (Face ID lock, at-rest encryption options).
20. Architecture RFC v1 published.

## 03. Capture & Editor

**Mandate:** See per-step goals below.

21. Implement Lock Screen & Control Center capture tiles (Idea/Task/Voice).
22. Share Sheet intake with provenance, quick classify to Project/Area.
23. Daily Log as default inbox; autosave; offline-first guarantees.
24. Voice capture with streaming transcription + live bookmarks.
25. Camera-to-text; screenshot OCR; reader-mode clean pipeline.
26. Editor inline Markdown converters; inline task grammar.
27. Pinch-to-outline + heading map; quick linker bar.
28. Focus mode (hide chrome); haptics; swipe grammar; multi-select.
29. Template gallery v1 (Daily/Meeting/Research/Creator).
30. QA checklist for capture latency (T2N P95 ≤ 900 ms).

## 04. Retrieval & AI

**Mandate:** See per-step goals below.

31. SQLite FTS baseline; vector store; hybrid search with rerank.
32. Natural-language Q&A scoped (Today/Project/Range/Selection).
33. Citations mandatory with paragraph/audio timestamp anchors.
34. Answer budgets & graceful degradation when vectors rebuild.
35. Context scoping UI; show-your-work toggle (top passages).
36. On-device suggestions; Local-only suggestion pipeline.
37. Question presets (decisions/changes/next actions).
38. Cache planner for P95 ≤ 1.5 s (target 1.2 s warm).
39. Telemetry: citation CTR, Q&A success rate.
40. Security: no hidden uploads; redaction preview for opt-in cloud AI.

## 05. Resurfacing & Insights

**Mandate:** See per-step goals below.

41. Morning brief (5–7 items) weighted by urgency/links/recency.
42. Weekly synthesis auto-note: highlights, decisions, open loops.
43. Dormant resurfacing (forgotten but relevant).
44. Sequence detection to stitch proposal→feedback→revision threads.
45. People-centric recall before meetings (calendar hook).
46. Time-boxed flashbacks (On this day).
47. Criticality scoring glyph, private.
48. Accept/ignore tracking to tune heuristics.
49. Energy-aware scheduling for resurfacing jobs.
50. Resurfacing A/B experiment plan.

## 06. Import/Export & Migration

**Mandate:** See per-step goals below.

51. Apple Notes importer with PARA mapping.
52. Obsidian vault open/import (front-matter/backlinks).
53. Notion export intake; relation reconstruction as links.
54. Import dry-run analyzer with counts/conflicts/dedupes.
55. Post-import Migration Deck (report).
56. Export everything (Markdown/JSON/attachments) one tap.
57. Snapshot publish (read-only) with checksum + expiry option.
58. Data integrity tests; attachment hash checks.
59. Large-vault performance test plan (5k–20k notes).
60. Docs: migration guides & FAQs.

## 07. Sync & Security

**Mandate:** See per-step goals below.

61. iCloud Drive vault path conventions & guidance.
62. E2E Private Sync: device key gen, rotation, recovery.
63. Selective sync folders; version history.
64. Conflict resolution: preserve both with inline markers.
65. Per-vault Face ID/passcode; app lock; inactivity lock.
66. Threat model & pen-test plan; dependency audit.
67. Privacy labels + App Store compliance artifacts.
68. Offline-first test matrix (airplane mode scenarios).
69. Recovery drills: backup/restore tests.
70. Security incident response runbook.

## 08. Performance, QA, Telemetry

**Mandate:** See per-step goals below.

71. Define SLOs & crash budgets; integrate into CI gates.
72. Cold vs warm path boot separation; measure T2N.
73. FTS & vector P95 measurement; query planner tuning.
74. OCR throughput targets; battery/thermal throttling tests.
75. End-to-end benchmarks vs baseline cohort (opt-in).
76. Test harness for importers; golden files.
77. Fuzz tests for share sheet/attachments.
78. Telemetry schemas (non-content) & opt-in path.
79. Matrix Monitor wires for SLO alerts.
80. Pre-launch test plan sign-off.

## 09. Go-To-Market, Pricing, Legal

**Mandate:** See per-step goals below.

81. Landing page build; waitlist; demo video.
82. App Store listing (screenshots/storyboard/keywords).
83. Beta partner outreach (education/creators).
84. Pricing page + in-app purchase flows; receipts handling.
85. Privacy policy, ToS, data processing appendix.
86. Support & refund policy; consent screens.
87. Content & social calendar (Friday Synthesis ritual).
88. Speed bake-off blog (time-to-note/Q&A).
89. Press kit (logo, screens, brand guide).
90. Launch checklist & D0/D7/D30 targets.

## 10. Operations, Support, Matrix Monitor

**Mandate:** See per-step goals below.

91. Matrix dashboard: progress bar, roadmap lanes, SLO tiles.
92. Daily Ops Brief auto-post; risk flags.
93. Support CRM setup; canned responses; issue form.
94. Crash triage pipeline; hotfix protocol.
95. Backlog grooming cadence (Train A/B/C).
96. Cohort analytics (activation, retention, conversion).
97. Template gallery updates process.
98. Localization pipeline (strings, RTL, CJK checks).
99. Quarterly roadmap review & rescore (RICE).
100. Postmortem template & incident review ritual.