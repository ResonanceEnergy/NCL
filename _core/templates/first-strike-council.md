# First Strike Council — Prompt & Query Reference

> Canonical prompt templates and lessons learned for the YouTube + X intelligence council system.
> Used by: NCL Awarebot-FPC pipeline, run-councils.sh, Paperclip council_sweep workflow

---

## Identity

The First Strike Council is a dual-source intelligence system that scrapes YouTube channels and X/Twitter feeds, transcribes and analyzes content, then synthesizes it into actionable intelligence via War Room briefing. It runs on Apple Silicon (M4 Pro) — no CUDA, no CrewAI, no heavy vector DB dependencies.

---

## Lessons Learned (Hard-Won)

### Architecture
- **Filesystem is the brain** — reports as .md + .json, signals as JSONL, alerts as individual JSON files. No vector DB needed for the intelligence pipeline. The folder structure IS the state.
- **Fallback chains over single backends** — every AI call uses Claude → Grok → Ollama local. Every X scan uses X API v2 → twscrape → Grok. Never depend on one provider.
- **Apple Silicon native** — use faster-whisper with CPU int8 quantization or mlx-whisper. Never reference CUDA, torch.cuda, or GPU compute_type=float16 on this machine.
- **No CrewAI** — too heavy, too many dependencies, adds a framework layer with no benefit for our use case. Plain async Python functions with httpx calls are simpler, faster, and debuggable.
- **No HuggingFace embeddings / ChromaDB** — unnecessary for intelligence scraping. Save that overhead for research-pipeline when we need semantic search.

### Scraping
- **yt-dlp is the YouTube backbone** — use `extract_flat` for metadata-only passes, `dateafter` for time filtering, and `playlistend` to cap results. Always `quiet=True, no_warnings=True`.
- **twscrape is fragile but useful** — no API key needed, uses logged-in account pool. Good for @agentbravo069 self-scraping and keyword search. Falls back gracefully when blocked.
- **X API v2 requires Bearer Token** — elevated access needed for trending. Use search as proxy for trending topics when you only have basic access.
- **Grok as X fallback is imprecise** — it returns natural language, not structured data. The `_parse_grok_posts()` function does best-effort extraction. Engagement numbers are approximate. Accept this.
- **Cache audio downloads** — check for `{video_id}.mp3` before re-downloading. yt-dlp doesn't deduplicate on its own.

### Transcription
- **faster-whisper int8 on CPU is fast enough** — the M4 Pro handles it well. Don't over-optimize. The `beam_size=5` + `vad_filter=True` settings are the sweet spot.
- **mlx-whisper is faster but optional** — install if you want native Metal acceleration, but faster-whisper CPU is the reliable default.
- **25MB limit on OpenAI Whisper API** — only use as cloud fallback for short videos. Most long-form content exceeds this.

### Analysis
- **Structured JSON output prompts work** — the system prompts in analyzer.py specify exact JSON schema. Models follow it ~90% of the time. The `_parse_analysis()` function handles edge cases.
- **Token cost awareness** — a full 24h transcription dump can be 50K+ tokens. The analyzers truncate to fit context windows. Keep prompts tight.
- **Confidence scores are the filter** — insights below 0.5 confidence are noise. Alerts only fire at 0.8+ with actionable=true.

### War Room
- **Actionable only** — the War Room prompt explicitly bans content creation suggestions. It produces SitRep, strategic assessment, risks/opportunities, and binding directives. Nothing else.
- **Directive routing is automatic** — War Room extracts binding directives and saves them to `mandate-generation/input/` as JSON. They sit there until NATRIX approves via the mandate approval gate.
- **AAC relay is conditional** — market/geopolitical signals at 0.7+ confidence get forwarded to AAC War Room. If the AAC directory doesn't exist, they're saved locally for later pickup.

---

## Prompt Templates

### YouTube Council Analysis Prompt

```
You are the NARTIX YouTube Intelligence Analyst. Analyze the following
video transcripts from the last 24 hours.

For each significant insight, provide:
{
  "insights": [
    {
      "title": "short descriptive title",
      "description": "2-3 sentence explanation",
      "category": "content|market|geopolitical|tech|music|culture|alt-science|gaming",
      "confidence": 0.0-1.0,
      "tags": ["tag1", "tag2"],
      "source_refs": ["video_id_1"],
      "actionable": true/false,
      "action_suggestion": "what to do about it"
    }
  ],
  "summary": "3-5 sentence executive summary of all content"
}

Focus on: signal over noise, cross-video patterns, emerging trends,
contradictions with known intelligence. Ignore filler content.
```

### X Council Analysis Prompt

```
You are the NARTIX X Intelligence Analyst. Analyze posts from three vectors:
1. Tracked accounts (what key people are saying)
2. Keyword search (what the market is discussing)
3. Trending topics (what's breaking)

Output structured JSON with insights covering:
- Sentiment landscape (bullish/bearish/neutral across topics)
- Convergence signals (same theme from multiple unrelated accounts)
- Information asymmetry (what smart money knows that retail doesn't)
- Risk alerts (anything that could impact NARTIX operations)

Same insight schema as YouTube Council.
```

### War Room Synthesis Prompt

```
You are the NARTIX War Room Commander. Synthesize YouTube + X council
intelligence into a strategic briefing.

Required sections:
1. SitRep — what happened in the last 24h
2. Intelligence Synthesis — cross-source convergence and contradictions
3. Strategic Assessment — SWOT + trend forecasts
4. Risks & Opportunities — ranked by severity with recommended actions
5. Binding Directives — max 5, each specific + time-bound + measurable
6. NCL Memory Flags — insights for long-term storage

Rules:
- NO content creation suggestions
- ONLY actionable intelligence
- Confidence scores on all assessments
- If intelligence is thin, say so — never fabricate
```

---

## Query Patterns (for interactive use)

### Quick Status
```
What did the last council sweep find? Summarize the latest
intelligence-scan/council-reports/ files.
```

### Targeted Recall
```
Search council reports for [topic]. What signals have we seen
in the last 7 days? Cross-reference YouTube and X sources.
```

### Convergence Detection
```
Are there any topics that appeared in BOTH YouTube transcripts
AND X posts this week? List them with confidence scores.
```

### Threat Assessment
```
Review the latest War Room briefing. Are there any unaddressed
risks? What directives are still pending in mandate-generation/input/?
```

### Source Expansion
```
Based on the last 3 council sweeps, which accounts or channels
are producing the highest-signal content? Should we add or remove
any from the tracked lists?
```

---

## File Locations

| Asset | Path |
|-------|------|
| YouTube scraper | `runtime/councils/youtube/scraper.py` |
| YouTube transcriber | `runtime/councils/youtube/transcriber.py` |
| YouTube analyzer | `runtime/councils/youtube/analyzer.py` |
| X scanner | `runtime/councils/xai/scanner.py` |
| X analyzer | `runtime/councils/xai/analyzer.py` |
| War Room bridge | `runtime/councils/shared/war_room_bridge.py` |
| Report writer | `runtime/councils/shared/report_writer.py` |
| Data models | `runtime/councils/shared/models.py` |
| Runner | `runtime/councils/runner.py` |
| Launch script | `run-councils.sh` |
| Council reports | `intelligence-scan/council-reports/` |
| Signals (JSONL) | `intelligence-scan/signals/` |
| Alerts (JSON) | `intelligence-scan/alerts/` |
| Directive relay | `mandate-generation/input/RLY-WAR-ROOM-*.json` |
