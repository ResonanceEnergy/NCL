import json
import pathlib


p = pathlib.Path("/Users/natrix/dev/NCL/data/portfolio/auto_trader/state.json")
if not p.exists():
    print("state.json not found")
    raise SystemExit(1)
s = json.loads(p.read_text())
print(
    f"BEFORE: active={s.get('active')} paused_by={s.get('paused_by')} "
    f"dd_pause={s.get('drawdown_halt_pause')} dd_band={s.get('drawdown_halt_band')}"
)
s["drawdown_halt_pause"] = False
s["drawdown_halt_band"] = "caution"
s["drawdown_halt_at_iso"] = None
s["active"] = True
s["paused_by"] = None
s["pause_reason"] = ""
p.write_text(json.dumps(s, indent=2, sort_keys=True))
print("OK cleared dd halt + activated")
print(
    f"AFTER:  active={s['active']} paused_by={s['paused_by']} "
    f"dd_pause={s['drawdown_halt_pause']} dd_band={s['drawdown_halt_band']}"
)
