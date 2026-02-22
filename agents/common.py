#!/usr/bin/env python3
import os
import json
import datetime
import subprocess
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
# PORTFOLIO = json.loads((ROOT / "portfolio.json").read_text(encoding="utf-8"))  # Load lazily

def get_portfolio():
    return json.loads((ROOT / "portfolio.json").read_text(encoding="utf-8"))

SENSITIVE_ACTIONS = set(CONFIG.get("require_consent_for", []))

class Log:
    @staticmethod
    def info(msg: str):
        print(f"[INFO] {msg}")

    @staticmethod
    def warn(msg: str):
        print(f"[WARN] {msg}")

    @staticmethod
    def error(msg: str):
        print(f"[ERROR] {msg}")


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def run_git(path: Path, args: List[str]) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(["git", "-C", str(path)] + args, capture_output=True, text=True, check=False)
        return cp.returncode, cp.stdout.strip(), cp.stderr.strip()
    except FileNotFoundError:
        return 127, "", "git not found"


def get_head_commit(path: Path) -> Optional[str]:
    rc, out, err = run_git(path, ["rev-parse", "HEAD"])
    return out if rc == 0 else None


def list_changed_files(path: Path, since_commit: Optional[str]) -> List[Tuple[str, str]]:
    if since_commit:
        rc, out, err = run_git(path, ["diff", "--name-status", f"{since_commit}..HEAD"])
    else:
        rc, out, err = run_git(path, ["show", "--name-status", "-m", "-1", "HEAD"])
    if rc != 0:
        return []
    rows: List[Tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split('\t')
        if len(parts) >= 2:
            status, fn = parts[0], parts[-1]
            rows.append((status, fn))
    return rows


def categorize_file(fn: str) -> str:
    fnl = fn.lower()
    if fnl.startswith(".ncl/") or "/.ncl/" in fnl:
        return "ncl"
    # detect test paths: either start with tests/ or contain /tests/
    if fnl.startswith("tests/") or any(seg in fnl for seg in ["/tests/", "/test/", "_test.", ".spec."]):
        return "tests"
    if any(fnl.endswith(ext) for ext in [".md", ".rst", ".txt"]):
        return "docs"
    return "code"


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat()


def load_mandate(repo_root: Path) -> Dict[str, Any]:
    mpath = repo_root / ".ncl" / "mandate.yaml"
    jpath = repo_root / ".ncl" / "mandate.json"
    if jpath.exists():
        return json.loads(jpath.read_text(encoding="utf-8"))
    data: Dict[str, Any] = {}
    if not mpath.exists():
        return data
    import io
    key = None
    for raw in io.StringIO(mpath.read_text(encoding="utf-8")):
        line = raw.rstrip('\n')
        if not line or line.strip().startswith('#'):
            continue
        if re.match(r"^[A-Za-z0-9_]+:\s*$", line):
            key = line.split(":")[0].strip()
            data[key] = None
        elif ":" in line and not line.lstrip().startswith("-"):
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip().strip('"')
        elif line.lstrip().startswith("- ") and key:
            if data.get(key) is None or not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(line.strip()[2:])
    return data


def require_consent_for(action_class: str) -> bool:
    return action_class in SENSITIVE_ACTIONS
