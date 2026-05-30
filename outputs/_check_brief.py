import json
import os


try:
    sz = os.path.getsize("/tmp/brief_14ae.json")
    print(f"file size: {sz}")
    with open("/tmp/brief_14ae.json") as f:
        env = json.load(f)
except Exception as e:
    print("parse error:", e)
    raise SystemExit
print("keys:", list(env.keys()))
text = env.get("full_brief", "")
print(f"brief text length: {len(text)}")
if "REDDIT PULSE" in text:
    idx = text.find("REDDIT PULSE")
    print("=" * 60)
    print("REDDIT PULSE section in rendered brief:")
    print("=" * 60)
    print(text[idx : idx + 1500])
else:
    print("REDDIT PULSE not in full_brief")
    intel = (env.get("lanes") or {}).get("intel") or {}
    top10 = intel.get("reddit_top10") or []
    print(f"lanes.intel.reddit_top10 count: {len(top10)}")
    if top10:
        print("sample:", json.dumps(top10[0], indent=2))
