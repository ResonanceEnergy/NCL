import json
from pathlib import Path
state = json.loads(Path("/Users/natrix/dev/NCL/data/portfolio/trade_ideas_state.json").read_text())
# Most recent 10 ideas
ideas = sorted(state.values(), key=lambda x: x.get("issued_at_iso", ""), reverse=True)[:10]
print(f"recent ideas:")
for i in ideas:
    print(f"  {i.get('issued_at_iso','?')[:19]}  src={i.get('source'):10s}  ticker={(i.get('ticker') or '?'):6s}  strategy={i.get('strategy'):10s}  entry={i.get('entry_price')}  stop={i.get('stop_price')}  target={i.get('target_price')}  R={i.get('R_per_share')}  sources={(i.get('sources') or [])[:1]}")
