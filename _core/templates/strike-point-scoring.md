# Strike Point — Scoring & Prioritization Reference

> Canonical reference for the Strike Point targeting system that gates all content
> entering the NCL intelligence pipeline. Nothing gets processed without Strike Point approval.

---

## Purpose

Strike Point is the precision targeting system that decides WHAT gets analyzed. It sits between raw scraping and AI analysis, enforcing the 24-hour duration cap on YouTube and relevance filtering on X posts. Without Strike Point, the pipeline would waste API budget analyzing noise.

---

## Lessons Learned (Hard-Won)

### Scoring Philosophy
- **Score, don't filter** — never hard-exclude content. Score everything, then let the greedy selector pick the best under the cap. A low-scoring video might be the only content available.
- **Keywords in title > description > tags** — title hits are 4x more predictive of relevance than description hits. Weight accordingly (2.0 / 0.5 / 1.0).
- **Recency is a tiebreaker, not a primary signal** — a 3-day-old video about first strike rations beats a 1-hour-old unrelated upload. Score handles this naturally.
- **View count is weak signal** — useful as a +1/+2 bonus, not a primary factor. Low-view niche content is often higher value than viral mainstream content.

### Duration Cap Enforcement
- **24 hours is a hard ceiling, not a target** — if only 2 hours of relevant content exists, process 2 hours. Don't pad with low-relevance filler to hit 24h.
- **Greedy selection works** — sort by score descending, add videos until cap is hit. No need for knapsack optimization — the marginal value difference between optimal and greedy is negligible when scores are well-calibrated.
- **Duration metadata comes free** — yt-dlp `extract_flat` includes duration. No need to download to check length. Never download just to discover a video is too long.

### X Post Filtering
- **twscrape user_tweets returns everything** — you MUST filter by date locally. The `since` parameter is enforced in our code, not by the API.
- **Keyword filtering on X is exact match** — `"first strike"` won't match `"First-Strike"`. Normalize to lowercase before comparison.
- **Self-scraping (@agentbravo069, @NathansMRE) should be unfiltered** — your own posts are always relevant. Only apply keyword filters to search results and trending.
- **Engagement is a better signal on X than YouTube** — high like/RT ratio on a niche topic = genuine signal. Weight engagement more heavily for X scoring.

### Pipeline Integration
- **Strike Point is NOT an AI call** — it's pure Python scoring logic. No API budget consumed. This is intentional — the gate should be free and fast.
- **The score travels with the video** — `video["strike_score"]` is preserved through download, transcription, and analysis. The analyzer can reference it for context.
- **Log the top hit** — always print the highest-scoring selection. This is the fastest diagnostic for "is Strike Point working right?"

---

## Scoring Algorithm (YouTube)

```python
def _strike_point_score(video: dict) -> float:
    score = 0.0
    title = video.get("title", "").lower()
    desc = video.get("description", "").lower()
    tags = " ".join(video.get("tags", [])).lower()

    for keyword in STRIKE_POINT_KEYWORDS:
        kw = keyword.lower()
        if kw in title:    score += 2.0   # Title is strongest signal
        if kw in desc:     score += 0.5   # Description is weak signal
        if kw in tags:     score += 1.0   # Tags are moderate signal

    # Recency bonus
    if uploaded_today:     score += 3.0
    elif uploaded_yesterday: score += 1.5

    # View count bonus (weak)
    if views >= 10000:     score += 2.0
    elif views >= 1000:    score += 1.0

    return score
```

### Score Interpretation

| Score Range | Meaning | Expected Action |
|-------------|---------|-----------------|
| 0.0 | No keyword match | Selected only if nothing else available |
| 0.5 - 2.0 | Weak match (description/tag only) | Selected if duration cap allows |
| 2.0 - 5.0 | Moderate match (title keyword) | Likely selected |
| 5.0 - 10.0 | Strong match (multiple keywords + recency) | Always selected |
| 10.0+ | Perfect target (multiple title keywords + today + views) | First in queue |

---

## Keyword Lists

### YouTube Strike Point Keywords
```
first strike, first-strike, FSR, MRE, ration, 24 hour, 24hr,
military ration, bass music, dubstep, substandard
```

### X Tracked Accounts
```
NathansMRE, agentbravo069, elikiingz, DeItaone, unusual_whales,
WatcherGuru, tier10k, MarioNawfal, wallaborealissys, ABOREALISSYS,
EndWokeness
```

### X Search Keywords
```
first strike ration, first-strike, FSR, 24 hour ration, MRE review,
AI agent framework, Claude Opus, Grok API, geopolitical risk,
prediction market, dubstep production, bass music, substandard bass,
unity game dev, Apple Silicon ML
```

---

## Tuning Guide

### Adding a new keyword
1. Add to `STRIKE_POINT_KEYWORDS` in `youtube/scraper.py`
2. Add to `DEFAULT_KEYWORDS` in `xai/scanner.py`
3. Run `./run-councils.sh --dry` to verify it picks up relevant content
4. Commit the change

### Adjusting score weights
- If too much irrelevant content passes: increase title weight, decrease desc/tag weight
- If too little content passes: add more keywords, lower the implicit threshold (it's currently 0 — everything scores)
- If wrong videos are prioritized: adjust recency bonus or view count bonus

### Adding a new YouTube channel
1. Add URL to `DEFAULT_CHANNELS` in `youtube/scraper.py`
2. Or set `YOUTUBE_COUNCIL_CHANNELS` env var (comma-separated)
3. Consider adding channel-specific keywords to STRIKE_POINT_KEYWORDS

### Adding a new X account
1. Add handle to `DEFAULT_ACCOUNTS` in `xai/scanner.py`
2. Or set `X_COUNCIL_ACCOUNTS` env var (comma-separated)

---

## Query Patterns (for interactive use)

### Score Diagnostics
```
Run a dry sweep: ./run-councils.sh --dry
Check which videos were selected and their scores.
Are the right ones at the top?
```

### Keyword Gap Analysis
```
Review the last 5 council reports. Are there topics that keep
appearing in insights but aren't in our keyword lists?
Add them to Strike Point.
```

### Duration Utilization
```
How much of the 24h cap are we actually using per sweep?
If consistently under 4h, we might need more channels or
a longer lookback window.
```

### False Positive Audit
```
Of the last 10 videos processed, how many produced zero
actionable insights? Those are false positives — their keywords
matched but content was irrelevant. Adjust scoring or add
negative keywords.
```

---

## Anti-Patterns (Don't Do This)

| Anti-Pattern | Why It's Wrong | Do This Instead |
|-------------|----------------|-----------------|
| AI-powered scoring | Burns API budget on the gate itself | Pure Python keyword scoring is free and fast |
| Hard keyword filters | Rejects everything on quiet days | Score everything, select best available |
| Download-then-check-duration | Wastes bandwidth and disk | Use `extract_flat` metadata for duration |
| Same weights for all keywords | "MRE" is generic, "first strike ration" is specific | Weight multi-word phrases higher naturally (they get multiple hits) |
| Ignoring score=0 content | Sometimes there's no keyword match but it's the only content | Let the greedy selector handle it — some data beats no data |
