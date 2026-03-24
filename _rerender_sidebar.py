"""Re-render sidebar + subtitles onto existing segment videos.

Uses the FIXED fluency_engine.py filter builder to apply:
  - Semi-transparent data sidebar panel (right side)
  - SRT word-level subtitles
onto the base segment videos from the pipeline run.

Usage:
    python _rerender_sidebar.py
"""

import json
import shutil
import subprocess
from pathlib import Path

# --- Config ---
RUN_DIR = Path("reports/helix_news/daily_20260322_225307")
SEGMENTS = ["cold_open", "headlines", "market_pulse", "predictions", "alerts", "closing"]

# Segments with multi-clip fluency plans (the ones that got the sidebar treatment)
MULTI_CLIP_SEGMENTS = {"cold_open", "headlines", "market_pulse", "predictions"}


def get_audio_duration(mp3_path: Path) -> float:
    """Get duration of an audio file via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(mp3_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip()) if result.returncode == 0 else 30.0


def main():
    # Load script
    script_path = RUN_DIR / "script.json"
    with open(script_path, encoding="utf-8") as f:
        script_data = json.load(f)

    segments = script_data["segments"]

    # Import the FIXED fluency engine
    import sys

    sys.path.insert(0, str(Path("ncl_agency_runtime/fpc/helix_news").resolve()))
    from fluency_engine import FluencyEngine

    fluency = FluencyEngine()

    # Get audio durations
    audio_durations = {}
    for seg in segments:
        name = seg["name"]
        mp3 = RUN_DIR / "audio" / f"{name}.mp3"
        if mp3.exists():
            audio_durations[name] = get_audio_duration(mp3)
            print(f"  {name}: {audio_durations[name]:.1f}s")

    # Generate fluency plans
    seg_dicts = [{"name": s["name"], "text": s["text"], "metadata": s.get("metadata", {})} for s in segments]
    plans = fluency.analyze(seg_dicts, audio_durations)

    # Re-render each segment with sidebar + subtitles
    for seg in segments:
        name = seg["name"]
        video_path = RUN_DIR / "video" / f"{name}.mp4"
        srt_path = RUN_DIR / "audio" / f"{name}.srt"
        output_path = RUN_DIR / "video" / f"{name}_overlay.mp4"

        if not video_path.exists():
            print(f"  {name}: SKIP (no video)")
            continue

        plan = plans.get(name)
        if not plan:
            print(f"  {name}: SKIP (no plan)")
            continue

        # Build filter string
        vf_parts = []

        # Sidebar overlay (only for segments with data)
        sidebar_vf = fluency.build_sidebar_drawtext_filters(plan, video_width=1280)
        if sidebar_vf:
            vf_parts.append(sidebar_vf)

        # Subtitles
        if srt_path.exists():
            srt_escaped = str(srt_path.resolve()).replace("\\", "/")
            vf_parts.append(
                f"subtitles='{srt_escaped}':force_style='FontSize=24,"
                f"PrimaryColour=&Hffffff&,OutlineColour=&H000000&,"
                f"Outline=2,Alignment=2,MarginV=40'"
            )

        if not vf_parts:
            print(f"  {name}: SKIP (no filters)")
            continue

        combined_vf = ",".join(vf_parts)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            combined_vf,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        print(f"  {name}: burning sidebar + subs...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  {name}: FAILED — {result.stderr[-300:]}")
        else:
            # Replace original with overlaid version
            shutil.move(str(output_path), str(video_path))
            print(f"  {name}: OK")


if __name__ == "__main__":
    print("=== Re-Rendering Sidebar + Subtitles ===")
    main()
    print("=== Done ===")
