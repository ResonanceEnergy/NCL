"""HELIX NEWS — Special Edition: The Private Credit Crash.

Bypasses the SignalScorer pipeline and injects a custom multi-segment
broadcast script, then runs TTS → Grok Imagine → Compositor for a
~3 minute special report.
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, ".")

# ── Load API keys from .env ──────────────────────────────────────────────────
env_path = r"C:\dev\DIGITAL LABOUR\DIGITAL LABOUR\.env"
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

key = os.environ.get("GROK_API_KEY", "")
print(f"GROK_API_KEY: {len(key)} chars")
if not key:
    print("ERROR: GROK_API_KEY not found in .env — cannot run Grok Imagine")
    sys.exit(1)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("helix_special")

# ── Config ───────────────────────────────────────────────────────────────────
CONFIG_PATH = "ncl_agency_runtime/fpc/config/helix_news.json"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
EPISODE_DIR = Path("reports/helix_news") / f"special_{TIMESTAMP}"
EPISODE_DIR.mkdir(parents=True, exist_ok=True)

# ── Pre-written script (~450 words, ~3 minutes at 150 WPM) ──────────────────
# Based on live intelligence from FT, Reuters, Bloomberg — March 17-18 2026

SEGMENTS = [
    {
        "name": "cold_open",
        "text": (
            "This is Helix with a special edition breaking report. "
            "The private credit market is cracking. "
            "What was once Wall Street's most lucrative growth engine is now "
            "hemorrhaging capital as defaults spike, valuations crumble, and "
            "the biggest names in finance scramble to contain the damage. "
            "Here is what you need to know."
        ),
    },
    {
        "name": "headlines",
        "text": (
            "The headlines are brutal. Blackstone's flagship private credit "
            "fund just got hit with one point seven billion dollars in net "
            "redemptions over the first quarter alone. BlackRock was forced "
            "to gate its HPS Corporate Lending Fund after withdrawal requests "
            "surged to nine point three percent of net asset value. "
            "Morgan Stanley and Cliffwater have also limited withdrawals. "
            "This is not isolated. This is a pattern. "
            "Retail investors are pulling billions from private credit funds "
            "and publicly traded vehicles are now trading at steep discounts. "
            "The flood of redemptions threatens to stall one of "
            "Wall Street's most important sources of growth."
        ),
    },
    {
        "name": "market_pulse",
        "text": (
            "The numbers tell a grim story. Partners Group, the Swiss private "
            "capital giant, is sounding the alarm on default rates, warning "
            "they could double to above five percent in coming years. "
            "JPMorgan is actively marking down loan portfolios of private "
            "credit groups, which will limit future lending to higher-risk "
            "borrowers. Glendon Capital Management is publicly questioning "
            "valuations in Blue Owl's portfolio, saying debts are marked "
            "above comparable publicly traded securities. "
            "Davidson Kempner's Tony Yoseloff, one of the top credit hedge "
            "fund managers, warned this week that Wall Street is "
            "underestimating the problem and that a substantial portion "
            "of private equity firms are already stressed or distressed."
        ),
    },
    {
        "name": "predictions",
        "text": (
            "So where does this go? Deutsche Bank CEO Christian Sewing says "
            "the noise around private credit will persist but does not see "
            "systemic risk yet. UBS says it is comfortable with its exposure. "
            "But the smart money is positioning defensively. "
            "Intercontinental Exchange just launched a new platform to bring "
            "transparency to the private credit market, a tacit admission "
            "that opacity is fueling investor panic. "
            "Debt investors are offloading exposure to software companies, "
            "which are heavily financed by private credit. "
            "And BNP Paribas is betting that European private credit can "
            "defy the American downturn, pointing to stricter regulation "
            "and different market structure. The divergence between US "
            "and European private credit may become the defining trade "
            "of twenty twenty-six."
        ),
    },
    {
        "name": "closing",
        "text": (
            "The private credit reckoning is here. The question is not "
            "whether defaults will rise, but how fast. "
            "The gating of redemptions at BlackRock and Blackstone is the "
            "canary in the coal mine. When the biggest funds lock the exit "
            "doors, you pay attention. "
            "This has been a Helix News special edition. "
            "Stay sharp. Stay informed. I will see you at the next signal."
        ),
    },
]

# ── Grok Imagine scene prompts (per segment) ────────────────────────────────
SCENE_PROMPTS = {
    "cold_open": (
        "Dramatic futuristic news broadcast studio with red alert lighting, "
        "holographic displays showing PRIVATE CREDIT CRASH in bold text, "
        "crumbling financial charts, dark moody atmosphere with neon accents, "
        "cinematic wide shot, photorealistic, 16:9 aspect ratio"
    ),
    "headlines": (
        "Wall Street trading floor in chaos, multiple screens showing red "
        "downward arrows and REDEMPTION WAVE text, stressed traders, "
        "Bloomberg terminals glowing, dramatic overhead shot, "
        "photorealistic, 16:9"
    ),
    "market_pulse": (
        "Dark war room with massive wall of financial data screens showing "
        "credit default swap charts spiking upward, debt-to-equity ratios "
        "flashing red, JPMorgan and BlackRock logos visible on displays, "
        "emergency operations aesthetic, photorealistic, 16:9"
    ),
    "predictions": (
        "Futuristic holographic globe showing the Atlantic Ocean with USA "
        "and Europe highlighted, data streams flowing between continents, "
        "diverging trend arrows, crystal ball effect with probability "
        "overlays, sci-fi command center, photorealistic, 16:9"
    ),
    "closing": (
        "Elegant futuristic news studio closing shot with a single anchor "
        "desk under spotlight, city skyline through glass walls at dusk, "
        "subtle red warning glow fading to blue calm, NCC hologram logo, "
        "cinematic wide angle, photorealistic, 16:9"
    ),
}

# ── Pipeline ─────────────────────────────────────────────────────────────────


def main() -> None:
    from ncl_agency_runtime.fpc.helix_news.avatar_engine import AvatarEngine
    from ncl_agency_runtime.fpc.helix_news.compositor import Compositor
    from ncl_agency_runtime.fpc.helix_news.tts_engine import TTSEngine

    # Save script
    script_path = EPISODE_DIR / "script.json"
    script_data = {
        "title": "HELIX SPECIAL EDITION: The Private Credit Crash",
        "date": datetime.now().isoformat(),
        "segments": SEGMENTS,
        "total_words": sum(len(s["text"].split()) for s in SEGMENTS),
        "est_duration_seconds": sum(len(s["text"].split()) for s in SEGMENTS) / 150 * 60,
    }
    script_path.write_text(json.dumps(script_data, indent=2), encoding="utf-8")
    print(f"\nScript: {script_data['total_words']} words, ~{script_data['est_duration_seconds']:.0f}s")

    # Stage 1: TTS (with delay between segments to avoid 503 rate-limit)
    print("\n=== STAGE 1/3: Text-to-Speech ===")
    import time as _time

    tts = TTSEngine(CONFIG_PATH)
    audio_dir = EPISODE_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_results: dict = {}
    for i, seg in enumerate(SEGMENTS):
        name = seg["name"]
        text = seg["text"]
        audio_path = str(audio_dir / f"{name}.mp3")
        srt_path = str(audio_dir / f"{name}.srt")
        for attempt in range(3):
            result = tts.synthesize(text, audio_path, srt_path)
            if result.get("audio"):
                break
            print(f"  {name}: retry {attempt + 1}/3 after error...")
            _time.sleep(5 * (attempt + 1))
        audio_results[name] = result
        status = "OK" if result.get("audio") else f"FAIL: {result.get('error')}"
        print(f"  {name}: {status}")
        if i < len(SEGMENTS) - 1:
            _time.sleep(3)  # pace requests to avoid 503
    print(f"Audio: {len(audio_results)} segments synthesized")

    # Stage 2: Avatar (Grok Imagine)
    print("\n=== STAGE 2/3: Grok Imagine Avatar ===")
    avatar = AvatarEngine(CONFIG_PATH)
    video_dir = EPISODE_DIR / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    avatar_results: dict = {}
    for seg in SEGMENTS:
        name = seg["name"]
        audio_res = audio_results.get(name)
        if not audio_res or not audio_res.get("audio"):
            print(f"  {name}: SKIP (no audio)")
            continue

        video_path = video_dir / f"{name}.mp4"
        scene_prompt = SCENE_PROMPTS.get(name, "Professional news broadcast, photorealistic, 16:9")

        print(f"  {name}: generating scene...")
        result = avatar.render(
            audio_path=audio_res["audio"],
            output_path=str(video_path),
            segment_name=name,
            segment_text=scene_prompt,
            subtitle_path=audio_res.get("subtitles"),
        )
        avatar_results[name] = result
        status = result.get("engine", "?") if result.get("video") else f"FAIL: {result.get('error')}"
        print(f"  {name}: {status}")

    # Stage 3: Compose
    print("\n=== STAGE 3/3: Composing Episode ===")
    comp = Compositor(CONFIG_PATH)
    episode_path = str(EPISODE_DIR / "episode.mp4")
    compose_result = comp.compose(avatar_results, episode_path)

    # Summary
    print("\n" + "=" * 60)
    print("HELIX NEWS SPECIAL EDITION — COMPLETE")
    print("=" * 60)
    print(f"Episode dir: {EPISODE_DIR}")
    print(f"Final video: {compose_result.get('video', compose_result.get('error', 'none'))}")

    # Save manifest
    manifest = {
        "episode_id": f"HELIX_SPECIAL_{TIMESTAMP}",
        "title": "The Private Credit Crash",
        "episode_dir": str(EPISODE_DIR),
        "script": script_data,
        "audio": {k: {"audio": v.get("audio"), "subtitles": v.get("subtitles")} for k, v in audio_results.items()},
        "avatar": {
            k: {"video": v.get("video"), "engine": v.get("engine"), "scene_image": v.get("scene_image")}
            for k, v in avatar_results.items()
        },
        "final_video": compose_result.get("video"),
    }
    (EPISODE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"Manifest: {EPISODE_DIR / 'manifest.json'}")


if __name__ == "__main__":
    main()
