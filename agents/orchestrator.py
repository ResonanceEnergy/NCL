#!/usr/bin/env python3
"""
Departmental Operations Orchestrator
Updated for departmental restructuring - coordinates system monitoring operations
"""

import subprocess, sys
from pathlib import Path

# Updated paths for departmental structure
ROOT = Path(__file__).parent.parent
SENTRY = ROOT/"departments"/"operations_command"/"system_monitoring"/"repo_sentry.py"
DAILY = ROOT/"departments"/"operations_command"/"system_monitoring"/"daily_brief.py"

# Simple logging
def log(message: str, level: str = "INFO"):
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")

def main():
    log("Running Departmental Operations Orchestrator…")
    log("Department: Operations Command - System Monitoring")

    # Change to departmental directory for proper imports
    dept_dir = ROOT/"departments"/"operations_command"/"system_monitoring"
    original_cwd = Path.cwd()

    try:
        import os
        os.chdir(dept_dir)

        log("Running Repo Sentry across portfolio…")
        cp = subprocess.run([sys.executable, "repo_sentry.py"])
        if cp.returncode != 0:
            log("Repo Sentry exited with non-zero code", "WARN")
        else:
            log("✅ Repo Sentry completed successfully")

        log("Compiling Daily Ops Brief…")
        cp = subprocess.run([sys.executable, "daily_brief.py"])
        if cp.returncode != 0:
            log("Daily Brief exited with non-zero code", "WARN")
        else:
            log("✅ Daily Brief completed successfully")

    finally:
        os.chdir(original_cwd)

    log("Departmental operations orchestration complete.")

if __name__ == '__main__':
    main()