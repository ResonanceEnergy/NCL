#!/usr/bin/env python3
"""
NCL Autonomous Daemon — Windows Scheduled Task Setup
═════════════════════════════════════════════════════
Creates a Windows Scheduled Task that starts the daemon on login
and keeps it running 24/7.

Usage:
    python setup_daemon_service.py install    — Create scheduled task
    python setup_daemon_service.py uninstall  — Remove scheduled task
    python setup_daemon_service.py status     — Check task status
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TASK_NAME = "NCL_AutonomousDaemon"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON_EXE = sys.executable
DAEMON_MODULE = "ncl_agency_runtime.runtime.autonomous_daemon"


def install():
    """Create Windows Scheduled Task for the daemon."""
    # Build the command
    cmd = f'"{PYTHON_EXE}" -m {DAEMON_MODULE} --interval 300 --max-tasks 10'
    working_dir = str(REPO_ROOT)

    # schtasks command to create a task that runs at logon
    schtasks_cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", cmd,
        "/SC", "ONLOGON",
        "/RL", "LIMITED",
        "/F",
    ]

    print(f"  Creating scheduled task: {TASK_NAME}")
    print(f"  Command: {cmd}")
    print(f"  Working directory: {working_dir}")
    print()

    try:
        result = subprocess.run(schtasks_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  Scheduled task '{TASK_NAME}' created successfully.")
            print("  The daemon will start automatically on next login.")
            print()
            print("  To start it now, run:")
            print(f"    schtasks /Run /TN {TASK_NAME}")
        else:
            print(f"  Error creating task: {result.stderr}")
            print()
            print("  You may need to run this as Administrator.")
            print(f"  Or start manually: {cmd}")
    except Exception as exc:
        print(f"  Error: {exc}")
        print(f"  Manual start: python -m {DAEMON_MODULE}")


def uninstall():
    """Remove the scheduled task."""
    try:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  Scheduled task '{TASK_NAME}' removed.")
        else:
            print(f"  Error: {result.stderr}")
    except Exception as exc:
        print(f"  Error: {exc}")


def status():
    """Check if the scheduled task exists and its status."""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(result.stdout)
        else:
            print(f"  Task '{TASK_NAME}' not found.")
            print("  Run: python setup_daemon_service.py install")
    except Exception as exc:
        print(f"  Error: {exc}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    action = sys.argv[1].lower()
    if action == "install":
        install()
    elif action == "uninstall":
        uninstall()
    elif action == "status":
        status()
    else:
        print(f"  Unknown action: {action}")
        print("  Use: install | uninstall | status")


if __name__ == "__main__":
    main()
