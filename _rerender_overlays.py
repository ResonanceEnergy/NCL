"""Re-render overlays on existing segment videos.

Applies sidebar drawtext + subtitles using two-pass approach to avoid
ffmpeg filter separator conflicts. Run after a pipeline that generated
video clips but failed on overlay burn.

Usage:
    python _rerender_overlays.py reports/helix_news/daily_20260322_231235
"""
import json
import subprocess
import sys
from pathlib import Path

# ── Setup ────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from ncl_agency_runtime.fpc.helix_news.fluency_engine import FluencyEngine  # noqa: E402

SEGMENTS = ["cold_open", "headlines", "market_pulse", "predictions", "alerts", "closing"]


def ffprobe_duration(path: str) -> float:
    """Get duration via ffprobe."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip()) if r.stdout.strip() else 0.0


def main(run_dir: str) -> None:
    rd = Path(run_dir)
    audio_dir = rd / "audio"
    video_dir = rd / "video"
    script_path = rd / "script.json"

    if not script_path.exists():
        print(f"ERROR: {script_path} not found")
        return

    script = json.load(open(script_path, encoding="utf-8"))
    segments_list = script["segments"]

    # Get audio durations for fluency planning
    audio_durations: dict[str, float] = {}
    for seg in SEGMENTS:
        mp3 = audio_dir / f"{seg}.mp3"
        if mp3.exists():
            audio_durations[seg] = ffprobe_duration(str(mp3))
            print(f"  {seg}: {audio_durations[seg]:.1f}s audio")

    # Generate fluency plans
    engine = FluencyEngine()
    plans = engine.analyze(segments_list, audio_durations)

    ok = 0
    fail = 0

    for seg in SEGMENTS:
        vid = video_dir / f"{seg}.mp4"
        srt = audio_dir / f"{seg}.srt"

        if not vid.exists():
            print(f"  SKIP {seg} — no video")
            continue

        plan = plans.get(seg)
        if not plan:
            print(f"  SKIP {seg} — no fluency plan")
            continue

        # Back up original
        bak = video_dir / f"{seg}_nooverlay.mp4"
        if not bak.exists():
            vid.rename(bak)
        src = str(bak)

        # Pass 1: sidebar drawtext
        sidebar_vf = engine.build_sidebar_drawtext_filters(plan, video_width=1280)
        if sidebar_vf:
            sidebar_out = str(video_dir / f"{seg}_sidebar.mp4")
            cmd1 = [
                "ffmpeg", "-y", "-i", src,
                "-vf", sidebar_vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "copy", "-movflags", "+faststart", sidebar_out,
            ]
            r1 = subprocess.run(cmd1, capture_output=True, text=True)
            if r1.returncode == 0:
                src = sidebar_out
                print(f"  {seg}: sidebar OK")
            else:
                print(f"  {seg}: sidebar FAIL — {r1.stderr[-300:]}")

        # Pass 2: subtitles
        if srt.exists():
            srt_escaped = str(srt.resolve()).replace("\\", "/").replace(":", "\\:")
            sub_vf = (
                f"subtitles='{srt_escaped}':force_style='FontSize=24,"
                f"PrimaryColour=&Hffffff&,OutlineColour=&H000000&,"
                f"Outline=2,Alignment=2,MarginV=40'"
            )
            cmd2 = [
                "ffmpeg", "-y", "-i", src,
                "-vf", sub_vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "copy", "-movflags", "+faststart", str(vid),
            ]
            r2 = subprocess.run(cmd2, capture_output=True, text=True)
            if r2.returncode == 0:
                print(f"  {seg}: subtitles OK")
                ok += 1
            else:
                print(f"  {seg}: subtitles FAIL — {r2.stderr[-300:]}")
                # Copy sidebar version (or original) as fallback
                import shutil
                shutil.copy2(src, str(vid))
                fail += 1
        else:
            # No subtitles — copy sidebar version as final
            import shutil
            shutil.copy2(src, str(vid))
            ok += 1
            print(f"  {seg}: no subtitles, sidebar only")

        # Clean up intermediate
        sidebar_tmp = video_dir / f"{seg}_sidebar.mp4"
        if sidebar_tmp.exists() and str(sidebar_tmp) != str(vid):
            sidebar_tmp.unlink(missing_ok=True)

    print(f"\nOverlay burn: {ok} OK, {fail} failed")

    # Re-composite episode
    print("\n=== Re-compositing episode ===")
    from ncl_agency_runtime.fpc.helix_news.compositor import Compositor

    comp = Compositor()
    seg_videos = {}
    for seg in SEGMENTS:
        vid = video_dir / f"{seg}.mp4"
        if vid.exists():
            seg_videos[seg] = {"video": str(vid), "engine": "rerender"}

    episode_path = str(rd / "episode.mp4")
    result = comp.compose(seg_videos, output_path=episode_path)
    if result.get("video"):
        size_mb = Path(result["video"]).stat().st_size / (1024 * 1024)
        print(f"Episode: {result['video']} ({size_mb:.1f}MB, {result.get('duration_seconds',0):.0f}s)")
    else:
        print(f"Compositor failed: {result}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python _rerender_overlays.py <run_dir>")
        sys.exit(1)
    main(sys.argv[1])
