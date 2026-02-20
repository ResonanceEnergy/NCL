import os
import sys
import subprocess
from pathlib import Path

# path hack
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(root)
sys.path.append(os.path.join(root, "agents"))

import agents.orchestrator as orchestrator
import agents.council as council
from agents import common


def test_orchestrator_main(tmp_path, monkeypatch):
    # prepare a fake repo and config
    # patch common config and ensure other modules see the same values
    cfg = {"repos_base": str(tmp_path), "reports_dir": str(tmp_path / "reports")}
    monkeypatch.setattr(common, "CONFIG", cfg)
    # repo_sentry and daily_brief imported earlier in tests may have their own copies
    import agents.repo_sentry as repo_sentry
    import agents.daily_brief as daily_brief
    monkeypatch.setattr(repo_sentry, "CONFIG", cfg)
    monkeypatch.setattr(daily_brief, "CONFIG", cfg)
    monkeypatch.setattr(orchestrator, "Log", common.Log)
    # adjust repos_base
    monkeypatch.setattr(repo_sentry, "REPOS_BASE", Path(str(tmp_path)))
    monkeypatch.setattr(daily_brief, "REPOS_BASE", Path(str(tmp_path)))
    # set portfolio for both modules
    monkeypatch.setattr(repo_sentry, "PORTFOLIO", {"repositories": [{"name": "Z"}]})
    monkeypatch.setattr(daily_brief, "PORTFOLIO", {"repositories": [{"name": "Z"}]})
    # recompute brief directory after changing config
    daily_brief.BRIEFS_DIR = Path(cfg["reports_dir"]) / "daily"
    daily_brief.ensure_dir(daily_brief.BRIEFS_DIR)

    # create repo Z and make a commit
    repo_root = tmp_path / "Z"
    repo_root.mkdir()
    subprocess.run(["git", "init", str(repo_root)], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Tester"], check=True)
    (repo_root / "a.txt").write_text("hello")
    subprocess.run(["git", "-C", str(repo_root), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "init"], check=True)

    # intercept subprocess.run so orchestration happens in-process with our patches
    original_run = subprocess.run
    def fake_run(cmd, *args, **kwargs):
        # if called to spawn one of our agent scripts, handle inline
        if isinstance(cmd, (list, tuple)) and len(cmd) > 1:
            script = str(cmd[1])
            if script.endswith("repo_sentry.py"):
                for r in repo_sentry.PORTFOLIO.get("repositories", []):
                    repo_sentry.process_repo(r["name"])
                # mimic CompletedProcess with stdout stderr
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if script.endswith("daily_brief.py"):
                daily_brief.build_portfolio_brief()
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        # otherwise delegate to real subprocess.run (needed for git commands etc)
        return original_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", fake_run)

    # run the orchestrator which should call sentry + brief
    orchestrator.main()

    # verify daily brief created
    import datetime
    brief = Path(common.CONFIG["reports_dir"]) / "daily" / f"brief_{datetime.date.today().isoformat()}.md"
    assert brief.exists()


def test_council_propose_function(tmp_path, monkeypatch):
    # use tmp decisions dir
    monkeypatch.setattr(common, "CONFIG", {"decisions_dir": str(tmp_path)})
    monkeypatch.setattr(council, "DECISIONS_DIR", Path(str(tmp_path)))

    # call evaluate + save_decision directly; ensure portfolio contains the repo
    monkeypatch.setattr(council, "PORTFOLIO", {"repositories": [{"name": "ANY"}]})
    proposal = {"repo": "ANY", "action": "foo", "autonomy": "L1", "risk": "MEDIUM", "id": "123"}
    decision = council.evaluate(proposal)
    assert decision["approved"]
    council.save_decision(proposal, decision)
    files = list(tmp_path.glob("decision_*.json"))
    assert files
