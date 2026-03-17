"""Run HELIX NEWS episode with Grok Imagine visuals."""
import os
import sys

sys.path.insert(0, ".")

# Load API keys from .env
env_path = r"C:\dev\DIGITAL LABOUR\DIGITAL LABOUR\.env"
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

key = os.environ.get("GROK_API_KEY", "")
print(f"GROK_API_KEY: {len(key)} chars")

from ncl_agency_runtime.fpc.helix_news import Producer  # noqa: E402

p = Producer(config_path="ncl_agency_runtime/fpc/config/helix_news.json")
print(f"Episode dir: {p.episode_dir}")

result = p.produce()

# Summary
print("\n=== EPISODE RESULT ===")
print(f"ID: {result['episode_id']}")

stages = result.get("stages", {})
script = stages.get("script", {})
print(f"Script: {script.get('est_duration_display', '?')} / {script.get('total_words', 0)} words")

audio = stages.get("audio", {})
print(f"Audio: {len(audio)} segments")

avatar = stages.get("avatar", {})
if isinstance(avatar, dict):
    videos = [v.get("video") for v in avatar.values() if isinstance(v, dict) and v.get("video")]
    errors = [v.get("error") for v in avatar.values() if isinstance(v, dict) and v.get("error")]
    engines = [v.get("engine", "?") for v in avatar.values() if isinstance(v, dict) and v.get("video")]
    print(f"Avatar: {len(videos)} videos (engines: {set(engines)}), {len(errors)} errors")
    for e in errors[:2]:
        print(f"  Error: {e}")

compose = stages.get("compose", {})
print(f"Video: {compose.get('video', compose.get('error', 'none'))}")
print(f"Final: {result.get('final_video', 'none')}")
