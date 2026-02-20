#!/usr/bin/env python3
from pathlib import Path
import json, argparse, datetime, uuid
from common import CONFIG, PORTFOLIO, Log, ensure_dir, require_consent_for

DECISIONS_DIR = Path(CONFIG["decisions_dir"])
ensure_dir(DECISIONS_DIR)

VALID_AUTONOMY = ["L0","L1","L2","L3"]
VALID_RISK = ["LOW","MEDIUM","HIGH"]

def load_repo(repo_name: str):
    for r in PORTFOLIO.get("repositories", []):
        if r["name"] == repo_name:
            return r
    return None

def has_valid_consent(repo_root: Path, action_class: str) -> bool:
    consents_dir = repo_root / ".ncl" / "consents"
    if not consents_dir.exists():
        return False
    for f in consents_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if data.get("action_class") == action_class and data.get("ttl_valid", True):
                return True
        except Exception:
            pass
    return False

def evaluate(proposal: dict) -> dict:
    decision = {
        "id": proposal.get("id", str(uuid.uuid4())),
        "approved": False,
        "requires_human": False,
        "reason": [],
        "timestamp": datetime.datetime.now().astimezone().isoformat(),
    }
    repo = load_repo(proposal["repo"])
    if not repo:
        decision["reason"].append("Unknown repo")
        return decision

    autonomy = proposal.get("autonomy", "L1")
    risk = proposal.get("risk", "MEDIUM")
    if autonomy not in VALID_AUTONOMY:
        decision["reason"].append("Invalid autonomy level")
        return decision
    if risk not in VALID_RISK:
        decision["reason"].append("Invalid risk tier")
        return decision

    action_class = proposal.get("action", "")
    repo_root = Path(CONFIG["repos_base"]) / repo["name"]

    # business rule: any financial action always forces human review
    if action_class == "financial_actions":
        decision["reason"].append("Financial actions always require human review")
        decision["requires_human"] = True
        return decision

    if require_consent_for(action_class):
        if not has_valid_consent(repo_root, action_class):
            decision["reason"].append("Missing valid consent receipt for sensitive action")
            decision["requires_human"] = True
            return decision

    if autonomy == "L3":
        decision["reason"].append("L3 always requires human + council gate")
        decision["requires_human"] = True
        return decision

    if risk == "HIGH":
        decision["reason"].append("HIGH risk requires human review")
        decision["requires_human"] = True
        return decision

    decision["approved"] = True
    decision["reason"].append("Policy pass: consent satisfied and within autonomy/risk thresholds")
    return decision

def save_decision(proposal: dict, decision: dict):
    rid = proposal.get("repo")
    pid = decision["id"]
    out = DECISIONS_DIR / f"decision_{rid}_{pid}.json"
    out.write_text(json.dumps({"proposal": proposal, "decision": decision}, indent=2), encoding='utf-8')
    Log.info(f"Decision written: {out}")

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['propose'])
    ap.add_argument('--repo', required=True)
    ap.add_argument('--action', required=True)
    ap.add_argument('--description', required=True)
    ap.add_argument('--risk', default='MEDIUM', choices=VALID_RISK)
    ap.add_argument('--autonomy', default='L1', choices=VALID_AUTONOMY)
    ap.add_argument('--id', default=None)
    args = ap.parse_args()

    proposal = {
        "id": args.id or str(uuid.uuid4()),
        "repo": args.repo,
        "action": args.action,
        "description": args.description,
        "risk": args.risk,
        "autonomy": args.autonomy
    }
    decision = evaluate(proposal)
    save_decision(proposal, decision)
    print(json.dumps(decision, indent=2))