"""Run HELIX NEWS clip production — one clip per ranked topic."""
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

from ncl_agency_runtime.fpc.helix_news.clip_producer import ClipProducer  # noqa: E402

max_clips = int(sys.argv[1]) if len(sys.argv) > 1 else 10

cp = ClipProducer(config_path="ncl_agency_runtime/fpc/config/helix_news.json")
print(f"Clips dir: {cp.clips_dir}")
print(f"Max clips: {max_clips}")

result = cp.produce_clips(max_clips=max_clips)

print("\n=== CLIP RESULTS ===")
print(f"Batch: {result['batch_id']}")
print(f"Total unique topics: {result['total_topics']}")
print(f"Clips produced: {result['clips_produced']}")
print(f"Clips failed: {result['clips_failed']}")
print()

for clip in result["clips"]:
    status = "OK" if clip.get("video") else "FAIL"
    topic = clip["topic"][:55]
    grade = clip.get("grade", "?")
    score = clip.get("score", 0)
    engine = clip.get("engine", "?")
    print(f"  [{status}] [{grade}] {score:.3f} | {engine:15s} | {topic}")
    if clip.get("error"):
        print(f"         Error: {clip['error']}")

print(f"\nOutput: {result['clips_dir']}")
