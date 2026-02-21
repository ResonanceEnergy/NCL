#!/usr/bin/env python3
from pathlib import Path
import json, datetime
from common import CONFIG, PORTFOLIO, Log, ensure_dir

REPOS_BASE = Path(CONFIG["repos_base"])
BRIEFS_DIR = Path(CONFIG["reports_dir"]) / "daily"
ensure_dir(BRIEFS_DIR)

def collect_repo_summary(repo_name: str):
    repo_root = REPOS_BASE / repo_name
    reports_dir = repo_root / "reports"
    today = datetime.date.today().isoformat()

    summary = {"repo": repo_name, "today": today, "commits": 0, "delta": None}
    jpath = reports_dir / f"delta_plan_{today}.json"
    if jpath.exists():
        try:
            summary["delta"] = json.loads(jpath.read_text(encoding='utf-8'))
        except Exception:
            pass
    if summary["delta"]:
        code = summary["delta"]["summary"].get("code",0)
        tests = summary["delta"]["summary"].get("tests",0)
        docs = summary["delta"]["summary"].get("docs",0)
        summary["commits"] = code + tests + docs
    return summary

def build_portfolio_brief():
    today = datetime.date.today().isoformat()
    lines = [f"# Daily Ops Brief — {today}", ""]
    focus = []
    for r in PORTFOLIO.get("repositories", []):
        name = r["name"]
        s = collect_repo_summary(name)
        if s["delta"]:
            d = s["delta"]
            lines.append(f"## {name}")
            lines.append(f"- Changes — code: {d['summary'].get('code',0)}, tests: {d['summary'].get('tests',0)}, docs: {d['summary'].get('docs',0)}, ncl: {d['summary'].get('ncl',0)}")
            if d.get("next_actions"):
                for a in d["next_actions"]:
                    lines.append(f"  - Next: {a}")
            lines.append("")
            if d['summary'].get('ncl',0) or d['summary'].get('code',0) > 5:
                focus.append(name)
    if focus:
        lines.insert(2, f"**Focus:** {', '.join(focus)}\n")
    out = BRIEFS_DIR / f"brief_{today}.md"
    out.write_text("\n".join(lines), encoding='utf-8')
    Log.info(f"Wrote {out}")
def queue_for_brief(enrich_file: Path) -> bool:
    """Queue enriched content for tomorrow's ops brief"""
    try:
        if not enrich_file.exists():
            Log.error(f"Enrichment file not found: {enrich_file}")
            return False

        enrich_data = json.loads(enrich_file.read_text(encoding='utf-8'))

        # Create a queued item file for tomorrow's brief
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        queued_dir = BRIEFS_DIR / "queued" / tomorrow
        ensure_dir(queued_dir)

        video_id = enrich_data["video_id"]
        queue_file = queued_dir / f"secondbrain_{video_id}.json"

        queue_item = {
            "type": "second_brain_ingestion",
            "video_id": video_id,
            "source_url": enrich_data.get("source_url"),
            "abstract": enrich_data.get("abstract_120w", "")[:200] + "...",
            "confidence": enrich_data.get("confidence", "unknown"),
            "action_items": enrich_data.get("action_items", []),
            "key_insights": enrich_data.get("key_insights", [])[:3],  # Top 3 insights
            "doctrine_principles": enrich_data.get("doctrine_map", {}).get("principles", []),
            "queued_at": datetime.datetime.now().isoformat(),
            "enrich_file": str(enrich_file)
        }

        queue_file.write_text(json.dumps(queue_item, indent=2), encoding='utf-8')
        Log.info(f"Queued {video_id} for {tomorrow} ops brief")
        return True

    except Exception as e:
        Log.error(f"Failed to queue for brief: {e}")
        return False
