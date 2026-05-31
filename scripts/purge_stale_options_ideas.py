"""Wave 14CU — purge pre-14CT-v2 options ideas with bogus prices.

The brief's options ideas before Wave 14CT-v2 (~22:36 ET 5/30) were
emitted with stock-style entry/stop/target that mixed option premium
with underlying-stock price. Examples now in trade_ideas_state.json:
  MSFT options: entry=450, stop=350, target=40  (target<entry nonsense)
  ASTS options: entry=110, stop=30,  target=50  (asymmetric R)

These keep the auto-trader's heat-cap saturated even though they'll
never legitimately fire (planned_qty=100 × R=$100 → $10K effective_R,
breaching the 25% NAV cap of $9K).

Strategy: mark them outcome="superseded" so the tracker keeps them
in history but the loop's `outcome == "emitted"` filter excludes
them. This is idempotent and reversible (we can flip back to
"emitted" later if a proper schema lands).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE = Path.home() / "dev" / "NCL" / "data" / "portfolio" / "trade_ideas_state.json"

# Heuristic: stale options = strategy="options" + (target_price < entry_price
# OR stop_price > entry_price OR no R_per_share computed).
# Wave 14CT-v2 (commit 1cbc390) explicitly skips options at registration,
# so any "emitted" options idea in the file is pre-14CT-v2 residue.


def main(dry_run: bool = False) -> dict:
    if not STATE.exists():
        print(f"no state file at {STATE}")
        return {"purged": 0}
    raw = json.loads(STATE.read_text())
    backup = STATE.with_suffix(f".pre-purge-{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak")
    if not dry_run:
        backup.write_text(json.dumps(raw, indent=2, sort_keys=True))

    purged = 0
    suspect = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for tid, idea in raw.items():
        if not isinstance(idea, dict):
            continue
        if idea.get("strategy") != "options":
            continue
        if idea.get("outcome") != "emitted":
            continue
        entry = idea.get("entry_price")
        stop = idea.get("stop_price")
        target = idea.get("target_price")
        # Sanity: target < entry → wrong direction or premium/underlying mix
        nonsense = False
        if entry and target and target < entry:
            nonsense = True
        if entry and stop and stop > entry * 1.5:
            nonsense = True  # stop above entry by >50% is options residue
        if nonsense or not idea.get("R_per_share"):
            purged += 1
            suspect.append({
                "trade_idea_id": tid,
                "ticker": idea.get("ticker"),
                "entry": entry, "stop": stop, "target": target,
                "R_per_share": idea.get("R_per_share"),
            })
            if not dry_run:
                idea["outcome"] = "superseded"
                idea["closed_at_iso"] = now_iso
                idea["notes"] = (
                    (idea.get("notes") or "")
                    + " | Wave 14CU: purged pre-14CT-v2 options with "
                      "schema-confused prices"
                ).strip(" |")

    if not dry_run:
        STATE.write_text(json.dumps(raw, indent=2, sort_keys=True))

    print(f"{'DRY RUN' if dry_run else 'PURGED'}: {purged} stale options ideas")
    for s in suspect:
        print(f"  {s['ticker']:6s} entry={s['entry']} stop={s['stop']} "
              f"target={s['target']} R={s['R_per_share']}  tid={s['trade_idea_id']}")
    if not dry_run:
        print(f"backup at: {backup}")
    return {"purged": purged, "suspect": suspect}


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
