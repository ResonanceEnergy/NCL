# Helix News — Deep Dive Research Document
## AI Avatar News Anchor for NCC Daily Briefings

**Version**: 1.0.0  
**Date**: 2026-03-12  
**Project**: Helix News Channel  
**Scope**: FPC + NCL + NCC-Doctrine ecosystem  

---

## 1. Executive Summary

Helix News is an automated AI news channel where a virtual avatar named **Helix** presents daily briefings in a professional news anchor format. Each episode (~10 minutes) covers:

1. **Last 24 hours** — what actually happened across all monitored domains
2. **Upcoming predictions** — what the FPC council forecasts next
3. **Breaking signals** — high-priority alerts requiring immediate attention
4. **Research updates** — progress across NCC repos and projects

The system is entirely automated: data aggregation → script generation → voice synthesis → avatar rendering → video composition → multi-channel delivery.

---

## 2. Technology Landscape — Avatar & Talking Head

### 2.1 Open Source (Local GPU)

#### SadTalker (★ 13.6k)
- **What**: Single portrait image + audio → talking head video
- **How**: 3D motion coefficients from audio, drives facial animation
- **License**: Apache 2.0 (commercial OK)
- **Input**: One still image + WAV audio
- **Output**: MP4 video with lip-synced talking head
- **Requirements**: Python 3.8, PyTorch, CUDA, ffmpeg
- **Quality**: Good lip sync, some artifacts at edges
- **Speed**: Near real-time on RTX 4090, slower on older GPUs
- **CLI**: `python inference.py --driven_audio audio.wav --source_image portrait.png --enhancer gfpgan`
- **Best for**: Quick automated generation, good enough quality
- **Limitations**: Face-only (no gestures), occasional artifacts

#### LivePortrait (★ 17.9k)
- **What**: Efficient portrait animation with stitching and retargeting
- **How**: Implicit keypoint-based motion transfer
- **License**: Custom (research + commercial both allowed)
- **Input**: Source image/video + driving video
- **Output**: Animated portrait MP4
- **Requirements**: Python 3.10, PyTorch, CUDA, ffmpeg
- **Quality**: Superior to SadTalker — better stitching, more natural
- **Speed**: Real-time on RTX 4090, 20x slower on CPU/MPS
- **Features**: Full body mode, expression editing, video-to-video
- **Windows**: One-click installer available on HuggingFace
- **Best for**: Highest quality local generation
- **Limitations**: Needs driving video (not direct audio-driven)
- **Audio-driven**: Via community project `ditto-talkinghead` for real-time audio→talking head

### 2.2 Commercial APIs

#### HeyGen (Streaming Avatar SDK)
- **Status**: ⚠️ Interactive Avatar SUNSETTING March 31, 2026 — migrating to LiveAvatar
- **What**: Real-time AI avatars via WebSocket streaming
- **SDK**: `@heygen/streaming-avatar` (npm/TypeScript)
- **Features**: Text-to-speech, event-driven, session management
- **Pricing**: Enterprise (API key), Creator/Teams (trial token)
- **Concurrent sessions**: 3 during testing
- **Best for**: Real-time interactive avatars (NOT batch video generation)
- **Limitation**: Sunsetting soon, TypeScript SDK only, no Python SDK

#### D-ID
- **What**: Create Talk API — generate talking head videos from image + audio/text
- **API**: REST endpoint `POST /talks`
- **Input**: Source image URL + audio/text script
- **Output**: MP4 video URL
- **Pricing**: Pay-per-video, free trial credits
- **Python**: REST API via `requests` library
- **Best for**: Cloud-hosted, no GPU needed
- **Limitation**: Per-video cost, API dependency

#### Synthesia
- **What**: Enterprise AI video generation platform
- **Features**: 230+ avatars, 140+ languages, branded templates
- **Best for**: Corporate/enterprise video production
- **Limitation**: Expensive, enterprise-focused, not suitable for daily automated generation

### 2.3 Recommendation

**Primary (Local/Free)**: **SadTalker** — audio-driven, Apache 2.0, direct audio→video  
**Secondary (Better Quality)**: **LivePortrait** + audio-to-motion — superior quality  
**Premium Fallback**: **D-ID API** — cloud-hosted, no GPU required  

---

## 3. Technology Landscape — Text-to-Speech (TTS)

### 3.1 Free / No API Key

#### edge-tts (★ 10.3k)
- **What**: Microsoft Edge's online TTS service, no API key needed
- **License**: GPL-3.0
- **Install**: `pip install edge-tts`
- **Quality**: Very good (Microsoft Neural voices)
- **Voices**: 300+ voices across 80+ locales
- **Features**: Rate/volume/pitch control, SRT subtitle generation
- **Speed**: Streaming, very fast
- **Python API**: Async, simple
- **CLI**: `edge-tts --text "Hello" --voice en-US-AriaNeural --write-media output.mp3 --write-subtitles output.srt`
- **Best voices for news**: `en-US-AriaNeural` (female, professional), `en-US-GuyNeural` (male, professional)
- **Killer feature**: Auto-generates SRT subtitles with word-level timing
- **Limitation**: Requires internet, Microsoft service dependency

### 3.2 Open Source (Local GPU)

#### Coqui TTS XTTS v2 (★ 44.8k)
- **What**: Deep learning TTS with voice cloning
- **License**: MPL-2.0
- **Install**: `pip install TTS`
- **Quality**: Excellent, especially XTTS v2
- **Features**: Voice cloning from 6-second sample, 16 languages, <200ms streaming
- **VRAM**: ~6-8GB for inference
- **Python API**: `tts.tts_to_file(text="...", speaker_wav="voice.wav", language="en", file_path="output.wav")`
- **Best for**: Custom "Helix" voice with voice cloning
- **Limitation**: Requires GPU, no free voice presets for news-style

#### Bark (★ 39k, Suno AI)
- **What**: Generative text-to-audio model (not just speech)
- **License**: MIT
- **Quality**: Highly realistic, can add laughs, sighs, pauses
- **Features**: 100+ voice presets, 13 languages, can generate music/effects
- **Limitation**: ~13 second output limit per generation (need chunking for long text)
- **VRAM**: 12GB full model, 2GB with small model + CPU offload
- **Best for**: Natural-sounding speech with emotional nuance
- **Limitation**: Inconsistent, GPT-style — can deviate from script

### 3.3 Commercial

#### ElevenLabs API
- **What**: Industry-leading TTS API
- **Quality**: Best-in-class naturalness
- **Features**: Voice cloning, multilingual, streaming, word-level timing
- **Pricing**: Free tier (10k chars/mo), Starter $5/mo (30k), Creator $22/mo (100k)
- **Python**: `pip install elevenlabs`
- **Models**: `eleven_multilingual_v2`, `eleven_turbo_v2_5`
- **Best for**: Premium quality when budget allows
- **Output formats**: MP3, PCM, WAV at various sample rates

### 3.4 Recommendation

**Primary (Free/Fast)**: **edge-tts** — no API key, SRT generation, great quality  
**Secondary (Custom Voice)**: **Coqui TTS XTTS v2** — clone a custom "Helix" voice  
**Premium**: **ElevenLabs** — best quality when budget allows  

---

## 4. Technology Landscape — Video Composition

### 4.1 MoviePy (★ 14.4k)
- **What**: Python video editing library
- **License**: MIT
- **Install**: `pip install moviepy`
- **Features**: Cuts, concatenation, text overlays, compositing, transitions
- **Use for**: Lower-thirds, headline banners, data overlays, segment transitions
- **Example**:
  ```python
  from moviepy import VideoFileClip, TextClip, CompositeVideoClip
  clip = VideoFileClip("avatar.mp4")
  title = TextClip(font="Arial.ttf", text="BREAKING", font_size=40, color='red')
  final = CompositeVideoClip([clip, title.with_position(('left', 'bottom'))])
  final.write_videofile("output.mp4")
  ```

### 4.2 FFmpeg (Direct)
- **What**: Command-line video/audio processing
- **Use for**: Fast concatenation, format conversion, audio mixing
- **Best for**: Performance-critical operations, batch processing
- **Example**: `ffmpeg -i video.mp4 -i audio.mp3 -c:v copy -c:a aac output.mp4`

### 4.3 Recommendation

**Primary**: **MoviePy** for compositing (overlays, text, transitions)  
**Supporting**: **ffmpeg** for raw concat/mux operations  

---

## 5. News Production Design

### 5.1 Episode Structure (10-minute format)

| Segment | Duration | Content |
|---------|----------|---------|
| **Cold Open** | 0:15 | "This is Helix News. Here's what you need to know." |
| **Top Headlines** | 2:00 | 3-5 biggest events from last 24 hours |
| **Market Pulse** | 1:30 | Financial markets, crypto, economic indicators |
| **Domain Deep Dive** | 2:00 | Detailed look at highest-impact domain |
| **Prediction Spotlight** | 2:00 | Top FPC predictions ranked by signal score |
| **Alert Board** | 1:00 | Active alerts and breaking signals |
| **Research Briefing** | 0:45 | Updates from NCC repos and projects |
| **Closing** | 0:30 | "That's your daily brief. Helix out." |

### 5.2 Script Format

```
[COLD_OPEN]
Good morning. This is Helix, your NCC intelligence anchor. 
Today is {date}. Here's your daily brief.

[HEADLINES]
Our top story: {headline_1_summary}
{headline_1_detail}

Moving on: {headline_2_summary}
{headline_2_detail}

And: {headline_3_summary}

[MARKET_PULSE]
In markets today: {market_summary}
Bitcoin is currently at {btc_price}, {btc_direction} {btc_pct}% in the last 24 hours.
{additional_market_data}

[DOMAIN_DEEP_DIVE]
Let's take a closer look at {top_domain}.
{domain_analysis}

[PREDICTIONS]
The FPC council's top predictions:
Number one: {prediction_1} — rated {grade_1} with {confidence_1}% confidence.
Number two: {prediction_2} — rated {grade_2} with {confidence_2}% confidence.

[ALERTS]
{alert_count} active alerts to monitor:
{alert_details}

[RESEARCH]
From the research desk: {research_updates}

[CLOSING]
That's your daily brief for {date}. 
Stay sharp. Helix out.
```

### 5.3 Data Sources for Each Segment

- **Headlines**: NCL `make_daily_brief()` → NDJSON event logs → ranked by SignalScorer
- **Market Pulse**: FPC financial_markets data source + crypto_onchain
- **Domain Deep Dive**: Highest-scoring domain from `domain_health()` + recent predictions
- **Predictions**: FPC `rank_predictions()` → top N by impact_score
- **Alerts**: FPC `AlertEngine.scan()` + `get_active_alerts()`
- **Research**: Git commit logs from NCC repos, evolution tasks status

---

## 6. System Architecture

### 6.1 Pipeline Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   DATA LAYER    │     │  SCRIPT LAYER   │     │  MEDIA LAYER    │
│                 │     │                 │     │                 │
│ FPC Predictions │────▶│ Script Generator│────▶│ TTS Engine      │
│ NCL Daily Brief │     │ (news_script.py)│     │ (edge-tts)      │
│ Alert Engine    │     │                 │     │                 │
│ Signal Scorer   │     │ Produces:       │     │ Produces:       │
│ Event Logs      │     │ - Script text   │     │ - Audio WAV/MP3 │
│ Domain Health   │     │ - Segment list  │     │ - SRT subtitles │
│ Git Commits     │     │ - Metadata JSON │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ DELIVERY LAYER  │     │ COMPOSITOR LAYER│     │  AVATAR LAYER   │
│                 │     │                 │     │                 │
│ File Output     │◀────│ Video Compositor│◀────│ SadTalker       │
│ OpenClaw Gateway│     │ (MoviePy)       │     │                 │
│ Telegram/Discord│     │                 │     │ Produces:       │
│ YouTube (future)│     │ Adds:           │     │ - Talking head  │
│                 │     │ - Lower thirds  │     │   MP4 video     │
│                 │     │ - Headlines     │     │                 │
│                 │     │ - Data overlays │     │                 │
│                 │     │ - Transitions   │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### 6.2 Directory Structure

```
src/
└── helix_news/
    ├── __init__.py          # Package init
    ├── config.py            # Helix News configuration
    ├── script_generator.py  # Aggregates data → news script
    ├── tts_engine.py        # Text-to-speech (edge-tts / ElevenLabs / Coqui)
    ├── avatar_engine.py     # Talking head generation (SadTalker / D-ID)
    ├── compositor.py        # Video composition (MoviePy + ffmpeg)
    ├── producer.py          # Orchestrates full pipeline
    └── assets/
        ├── helix_portrait.png   # Helix avatar source image
        ├── intro_music.mp3      # Brief intro jingle
        ├── outro_music.mp3      # Closing jingle
        └── lower_third.png      # News bar template
```

### 6.3 Configuration

```json
{
  "helix_news": {
    "version": "1.0.0",
    "episode_max_minutes": 10,
    "tts": {
      "engine": "edge-tts",
      "voice": "en-US-AriaNeural",
      "rate": "+5%",
      "fallback_engine": "coqui",
      "fallback_voice_wav": "assets/helix_voice_sample.wav"
    },
    "avatar": {
      "engine": "sadtalker",
      "source_image": "assets/helix_portrait.png",
      "enhancer": "gfpgan",
      "fallback_engine": "d-id",
      "fallback_api_key_env": "DID_API_KEY"
    },
    "output": {
      "resolution": "1920x1080",
      "fps": 30,
      "format": "mp4",
      "output_dir": "reports/helix_news/"
    },
    "delivery": {
      "channels": ["file", "telegram", "discord"],
      "telegram_bot": true,
      "discord_webhook": true
    },
    "schedule": {
      "daily_brief_hour": 7,
      "timezone": "America/Montevideo"
    }
  }
}
```

---

## 7. Technology Comparison Matrix

### 7.1 TTS Engines

| Feature | edge-tts | Coqui XTTS v2 | ElevenLabs | Bark |
|---------|----------|----------------|------------|------|
| **Cost** | FREE | FREE (local) | $5-22/mo | FREE (local) |
| **API Key** | No | No | Yes | No |
| **Quality** | 8/10 | 9/10 | 10/10 | 7/10 |
| **Voice Cloning** | No | Yes (6s sample) | Yes | No (presets only) |
| **Subtitles** | SRT auto-gen | No | Word-level timing | No |
| **Streaming** | Yes | Yes (<200ms) | Yes | No |
| **GPU Required** | No | Yes (6-8GB) | No | Yes (2-12GB) |
| **Consistency** | High | High | High | Low (GPT-style) |
| **Max Length** | Unlimited | Unlimited | Unlimited | ~13s chunks |
| **Languages** | 80+ | 16 | 32 | 13 |

### 7.2 Avatar Engines

| Feature | SadTalker | LivePortrait | D-ID API | HeyGen |
|---------|-----------|--------------|----------|--------|
| **Cost** | FREE | FREE | Per-video | Enterprise |
| **License** | Apache 2.0 | Custom (OK) | Commercial | Commercial |
| **Input** | Image + Audio | Image + Video | Image + Text/Audio | API |
| **Audio-Driven** | ✅ Direct | ❌ (needs driver) | ✅ Direct | ✅ Direct |
| **Quality** | 7/10 | 9/10 | 8/10 | 9/10 |
| **GPU Required** | Yes (CUDA) | Yes (CUDA) | No | No |
| **Full Body** | Yes (still mode) | Yes | Shoulders up | Full |
| **Self-Hosted** | Yes | Yes | No (cloud) | No (cloud) |
| **Batch Generation** | Yes | Yes | Yes | No (streaming) |

### 7.3 Recommended Stack (Tiered)

#### Tier 1 — Free/Local (MVP)
- **TTS**: edge-tts (free, no GPU, SRT generation)
- **Avatar**: SadTalker (free, audio-driven, GPU required)
- **Compositor**: MoviePy + ffmpeg
- **Total cost**: $0 (just GPU electricity)

#### Tier 2 — Enhanced Quality
- **TTS**: Coqui XTTS v2 (custom "Helix" voice clone)
- **Avatar**: LivePortrait (higher quality animation)
- **Compositor**: MoviePy + ffmpeg
- **Total cost**: $0 (local GPU)

#### Tier 3 — Premium/Cloud
- **TTS**: ElevenLabs ($22/mo Creator plan)
- **Avatar**: D-ID API (pay per video)
- **Compositor**: MoviePy + ffmpeg
- **Total cost**: ~$50-100/mo

---

## 8. Implementation Phases

### Phase 1 — Script Generator (No GPU needed)
- Build `script_generator.py` that aggregates FPC + NCL data
- Format into news anchor script with segment structure
- Output: script text + metadata JSON
- Wire into `fpc helix-script` CLI command

### Phase 2 — Voice Synthesis (No GPU needed)
- Build `tts_engine.py` with edge-tts integration
- Convert script segments to audio files + SRT subtitles
- Support voice selection and rate control
- Wire into `fpc helix-audio` CLI command

### Phase 3 — Avatar Rendering (GPU needed)
- Build `avatar_engine.py` with SadTalker integration
- Generate talking head video from portrait + audio
- Add GFPGAN face enhancement
- Wire into `fpc helix-render` CLI command

### Phase 4 — Video Composition
- Build `compositor.py` with MoviePy
- Add lower-thirds, headline bars, data overlays
- Segment transitions with brief fades
- Wire into `fpc helix-compose` CLI command

### Phase 5 — Full Pipeline
- Build `producer.py` orchestrating all stages
- `fpc helix` → runs entire pipeline end-to-end
- Schedule via cron/Task Scheduler for daily generation
- Delivery via OpenClaw gateway to Telegram/Discord

---

## 9. Dependencies

### Required (Phase 1-2, No GPU)
```
edge-tts>=7.0         # Microsoft TTS (free, no key)
moviepy>=2.0          # Video composition
Pillow>=9.0           # Image processing
```

### Optional (Phase 3+, GPU)
```
# SadTalker dependencies (separate venv recommended)
torch>=1.12           # PyTorch with CUDA
torchvision
torchaudio
face-alignment
gfpgan                # Face enhancement
```

### Optional (Premium)
```
elevenlabs            # ElevenLabs TTS API
TTS>=0.22             # Coqui TTS (XTTS v2)
```

---

## 10. Key Decisions & Trade-offs

1. **edge-tts as primary TTS**: Free, high quality, SRT generation for subtitles, no GPU. Trade-off: requires internet, Microsoft service dependency.

2. **SadTalker as primary avatar**: Only open-source option that's directly audio-driven (no need for separate driving video). Trade-off: lower quality than LivePortrait.

3. **Segment-based generation**: Generate each segment separately, then compose. Trade-off: transitions between segments, but enables parallel processing and caching.

4. **MoviePy for composition**: Python-native, easy overlays. Trade-off: slower than raw ffmpeg for simple operations.

5. **Progressive deployment**: Script generator works without GPU (Phase 1-2). Avatar rendering added later when GPU available (Phase 3). Can use "audio-only" mode as podcast fallback.

---

## 11. Related Projects & Inspiration

- **Channel 1 AI** — AI-generated news channel (commercial)
- **Synthesia** — Enterprise AI video platform
- **Podcastfy** — Open source tool using edge-tts for podcast generation
- **ditto-talkinghead** — Real-time audio-driven talking head with LivePortrait
- **FasterLivePortrait** — TensorRT-accelerated LivePortrait

---

## 12. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| edge-tts service changes/blocks | High | Fallback to Coqui TTS or ElevenLabs |
| SadTalker quality insufficient | Medium | Upgrade to LivePortrait + ditto-talkinghead |
| GPU not available | High | D-ID API fallback, or audio-only podcast mode |
| 10-min video too large for Telegram | Low | Split into segments, or upload to file hosting |
| Script too long/short for 10 min | Medium | Dynamic segment scaling based on content volume |
| Avatar uncanny valley effect | Medium | Use cartoon/stylized avatar instead of photorealistic |

---

*Research compiled from: GitHub repositories, official documentation, API references, and community resources. All tools evaluated as of March 2026.*
