"""HELIX NEWS — Daily Intelligence Brief.

Pulls live data from the FPC predictions database (state/fpc.db),
generates a structured broadcast script via ScriptGenerator, then
runs the full pipeline: TTS → Grok Imagine → Compositor.

Helix appears as the on-camera anchor in every scene (protocol v2).

Usage::

    cd C:\\dev\\NCL
    C:\\Python314\\python.exe _run_helix_daily.py

Output: reports/helix_news/daily_YYYYMMDD_HHMMSS/episode.mp4
"""

import json
import logging
import os
import sys
import time
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
logger = logging.getLogger("helix_daily")

# ── Config ───────────────────────────────────────────────────────────────────
CONFIG_PATH = "ncl_agency_runtime/fpc/config/helix_news.json"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
EPISODE_DIR = Path("reports/helix_news") / f"daily_{TIMESTAMP}"
EPISODE_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    from ncl_agency_runtime.fpc.helix_news.avatar_engine import AvatarEngine
    from ncl_agency_runtime.fpc.helix_news.compositor import Compositor
    from ncl_agency_runtime.fpc.helix_news.fluency_engine import FluencyEngine
    from ncl_agency_runtime.fpc.helix_news.script_generator import ScriptGenerator
    from ncl_agency_runtime.fpc.helix_news.tts_engine import TTSEngine

    # ── Stage 0: Generate Script from live FPC data ───────────────────────
    print("\n=== STAGE 0/4: Generating Script from FPC Database ===")
    gen = ScriptGenerator(CONFIG_PATH)
    script = gen.generate()

    segments = script["segments"]
    print(f"Script: {script['total_words']} words, ~{script['est_duration_display']}")
    print(f"Segments: {', '.join(s['name'] for s in segments)}")

    # Save script copy to episode dir
    script_path = EPISODE_DIR / "script.json"
    script_path.write_text(json.dumps(script, indent=2, default=str), encoding="utf-8")

    # ── Stage 1: TTS ─────────────────────────────────────────────────────
    print("\n=== STAGE 1/4: Text-to-Speech ===")
    tts = TTSEngine(CONFIG_PATH)
    audio_dir = EPISODE_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_results: dict = {}

    for i, seg in enumerate(segments):
        name = seg["name"]
        text = seg["text"]
        audio_path = str(audio_dir / f"{name}.mp3")
        srt_path = str(audio_dir / f"{name}.srt")

        for attempt in range(3):
            result = tts.synthesize(text, audio_path, srt_path)
            if result.get("audio"):
                break
            print(f"  {name}: retry {attempt + 1}/3 after error...")
            time.sleep(5 * (attempt + 1))

        audio_results[name] = result
        status = "OK" if result.get("audio") else f"FAIL: {result.get('error')}"
        print(f"  {name}: {status}")

        if i < len(segments) - 1:
            time.sleep(3)  # pace edge-tts requests to avoid 503 rate-limit

    print(f"Audio: {sum(1 for v in audio_results.values() if v.get('audio'))}/{len(segments)} segments")

    # ── Stage 2: Fluency Analysis ────────────────────────────────────────
    print("\n=== STAGE 2/4: Fluency Engine — Clip Planning ===")
    fluency = FluencyEngine()

    # Get audio durations via ffprobe
    audio_durations: dict[str, float] = {}
    for name, ares in audio_results.items():
        if ares.get("audio"):
            import subprocess
            dur_result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", ares["audio"]],
                capture_output=True, text=True,
            )
            try:
                audio_durations[name] = float(dur_result.stdout.strip())
            except ValueError:
                audio_durations[name] = 30.0

    clip_plans = fluency.analyze(segments, audio_durations)
    for name, plan in clip_plans.items():
        dur = audio_durations.get(name, 0)
        print(f"  {name}: {dur:.1f}s → {len(plan.clips)} clips"
              f" (crossfade={plan.crossfade_duration:.1f}s)")

    # ── Stage 3: Avatar (Grok Video — fluency-driven) ────────────────────
    print("\n=== STAGE 3/4: Grok Video — Fluency-Driven Render ===")
    avatar = AvatarEngine(CONFIG_PATH)
    video_dir = EPISODE_DIR / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    avatar_results: dict = {}
    for seg in segments:
        name = seg["name"]
        text = seg["text"]
        audio_res = audio_results.get(name)

        if not audio_res or not audio_res.get("audio"):
            print(f"  {name}: SKIP (no audio)")
            continue

        video_path = video_dir / f"{name}.mp4"
        plan = clip_plans.get(name)
        print(f"  {name}: generating Helix scene ({len(plan.clips) if plan else '?'} clips)...")

        result = avatar.render(
            audio_path=audio_res["audio"],
            output_path=str(video_path),
            segment_name=name,
            segment_text=text,
            subtitle_path=audio_res.get("subtitles"),
            clip_plan=plan,
        )
        avatar_results[name] = result
        status = result.get("engine", "?") if result.get("video") else f"FAIL: {result.get('error')}"
        print(f"  {name}: {status}")

    # ── Stage 4: Compose ─────────────────────────────────────────────────
    print("\n=== STAGE 4/4: Composing Episode ===")
    comp = Compositor(CONFIG_PATH)
    episode_path = str(EPISODE_DIR / "episode.mp4")
    compose_result = comp.compose(avatar_results, episode_path)

    # ── Summary ───────────────────────────────────────────────────────────
    video_file = compose_result.get("video")
    duration = compose_result.get("duration_seconds", 0)

    print("\n" + "=" * 60)
    print("HELIX NEWS DAILY BRIEF — COMPLETE")
    print("=" * 60)
    print(f"Episode dir : {EPISODE_DIR}")
    print(f"Final video : {video_file or compose_result.get('error', 'none')}")
    if duration:
        print(f"Duration    : {duration:.1f}s ({duration / 60:.1f} min)")

    manifest = {
        "episode_id": f"HELIX_DAILY_{TIMESTAMP}",
        "title": f"Helix News Daily Brief — {datetime.now().strftime('%B %d, %Y')}",
        "episode_dir": str(EPISODE_DIR),
        "script": script,
        "audio": {k: {"audio": v.get("audio"), "subtitles": v.get("subtitles")} for k, v in audio_results.items()},
        "avatar": {
            k: {"video": v.get("video"), "engine": v.get("engine"), "scene_image": v.get("scene_image")}
            for k, v in avatar_results.items()
        },
        "final_video": video_file,
        "duration_seconds": duration,
    }
    manifest_path = EPISODE_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"Manifest    : {manifest_path}")


if __name__ == "__main__":
    main()
