# Helix News — Broadcast Protocol v2.0

## Overview

Helix is the NCC intelligence anchor. She appears on-camera in every scene.
This document defines her visual identity, segment structure, voice settings,
and the Grok Imagine prompt template that puts her in every frame.

---

## Helix Visual Identity (Grok Imagine Protocol)

Every Grok Imagine prompt MUST begin with this character description verbatim:

```
Helix, a professional AI news anchor, silver-chrome shoulder-length hair,
sharp angular facial features, luminous blue eyes, wearing a sleek dark navy
blazer with subtle circuit-pattern trim, seated at a futuristic illuminated
glass anchor desk, making direct fourth-wall eye contact with the camera,
confident composed expression
```

After this anchor block, append the scene-specific background environment
and end with: `photorealistic, 16:9`

Implementation: `avatar_engine.py` — `_HELIX_ANCHOR` ClassVar + `_SCENE_PROMPTS` ClassVar.

---

## Per-Segment Scene Prompts

| Segment | Background Environment |
|---|---|
| `cold_open` | Futuristic broadcast studio, holographic globe rotating behind her, global data feeds on screens, dramatic blue and purple studio lighting |
| `headlines` | Breaking news set, split-screen world event thumbnails flanking her, live news ticker scrolling below, modern newsroom aesthetic, dramatic key lighting |
| `market_pulse` | Financial trading floor background, wall of candlestick charts and market data screens, green and red indicators glowing, Bloomberg terminal aesthetic, dark room with screen-glow |
| `predictions` | Holographic probability charts and data streams surrounding her, neural network visualization in background, sci-fi command center, purple and blue neon glow |
| `alerts` | Emergency alert set, red warning indicators on screens behind her, urgent atmosphere, radar displays — expression: serious and urgent |
| `closing` | NCC logo hologram glowing behind her, city skyline visible through floor-to-ceiling windows, golden hour lighting, cinematic wide angle — expression: warm professional closing |

---

## Voice Settings

Configured in `ncl_agency_runtime/fpc/config/helix_news.json`:

```json
{
  "tts": {
    "voice": "en-US-AvaNeural",
    "rate": "+12%",
    "pitch": "+3Hz"
  }
}
```

TTS engine: `edge-tts` (Microsoft Azure Neural TTS via Bing).
Rate limit protection: 3-second sleep between segments, 3-attempt retry with 5s/10s/15s backoff.

---

## Segment Structure

Standard daily brief segment order (defined in `compositor.py`):

1. **cold_open** — Good morning/evening greeting, today's date, domain teaser
2. **headlines** — Top 5 events across all domains with domain tags
3. **market_pulse** — Finance domain predictions only (top 3)
4. **predictions** — Non-finance FPC council forecasts (top 5)
5. **alerts** — Active alert engine alerts (all-clear if none)
6. **closing** — Sign-off with next session preview

Target duration: 5–10 minutes at 150 WPM news anchor pace.

---

## Episode Runners

| Runner | Data Source | Use Case |
|---|---|---|
| `_run_helix_daily.py` | SQLite `state/fpc.db` via ScriptGenerator | Standard daily brief |
| `_run_helix_special.py` | Hardcoded custom script | Breaking news / special editions |
| `_run_helix_grok.py` | Producer class (full pipeline) | Full pipeline with SignalScorer |

---

## Pipeline Architecture

```
ScriptGenerator (SQLite fpc.db)
        ↓
    segments[]
        ↓
  TTSEngine (edge-tts)        → audio/*.mp3 + audio/*.srt
        ↓
  AvatarEngine (grok_imagine) → video/*.mp4  (Helix in-frame per _SCENE_PROMPTS)
        ↓
  Compositor                  → episode.mp4
        ↓
  manifest.json
```

Output directory: `reports/helix_news/daily_YYYYMMDD_HHMMSS/`

---

## Running a Daily Brief

```powershell
cd C:\dev\NCL
C:\Python314\python.exe _run_helix_daily.py
```

Full run time: ~15–25 minutes (Grok Imagine API + video rendering per segment).

---

## Version History

| Version | Date | Change |
|---|---|---|
| v1.0 | 2026-03-15 | Initial pipeline, static PNG backgrounds, Helix voiceover only |
| v1.1 | 2026-03-15 | Switched to grok_imagine engine, background scene prompts |
| v2.0 | 2026-03-18 | **Helix in-frame protocol** — character description added to all prompts, `_HELIX_ANCHOR` ClassVar, `_run_helix_daily.py` created |
