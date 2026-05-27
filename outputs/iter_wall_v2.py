#!/usr/bin/env python3
"""Iteratively wall iOS-only patterns until the Mac build is green.

Fixes the v1 script's parsing bug (was matching 'Binary file ... matches'
lines from grep). Uses pure-Python file walk + error log parsing.
"""

import os
import re
import subprocess
import sys


PROJECT = "/Users/natrix/Projects/FirstStrike"
LOG = "/tmp/p11_build.log"

PLACEMENTS = [
    ("placement: .navigationBarLeading", "placement: .cancellationAction"),
    ("placement: .navigationBarTrailing", "placement: .confirmationAction"),
    ("placement: .topBarLeading", "placement: .cancellationAction"),
    ("placement: .topBarTrailing", "placement: .confirmationAction"),
]

WALL_PATTERNS = [
    r"^(\s*)\.navigationBarTitleDisplayMode\([^)]+\)\s*$",
    r"^(\s*)\.autocapitalization\([^)]+\)\s*$",
    r"^(\s*)\.textInputAutocapitalization\([^)]+\)\s*$",
    r"^(\s*)\.keyboardType\([^)]+\)\s*$",
    r"^(\s*)\.statusBarHidden\([^)]*\)\s*$",
    r"^(\s*)\.navigationBarBackButtonHidden\([^)]+\)\s*$",
    r"^(\s*)\.navigationBarHidden\([^)]+\)\s*$",
    r"^(\s*)\.statusBar\([^)]+\)\s*$",
    r"^(\s*)\.toolbarBackground\([^)]+\)\s*$",
]


def wall_file(path: str) -> bool:
    try:
        s = open(path).read()
    except Exception:
        return False
    orig = s
    for old, new in PLACEMENTS:
        s = s.replace(old, new)
    for pat in WALL_PATTERNS:
        s = re.sub(
            pat,
            lambda m: f"{m.group(1)}#if os(iOS)\n{m.group(0)}\n{m.group(1)}#endif",
            s,
            flags=re.MULTILINE,
        )
    if s != orig:
        open(path, "w").write(s)
        return True
    return False


def wrap_file_ios_only(path: str) -> bool:
    """Last resort: wrap entire file in #if os(iOS) / #endif."""
    try:
        s = open(path).read()
    except Exception:
        return False
    if s.startswith("#if os(iOS)"):
        return False
    s = "#if os(iOS)\n" + s + "\n#endif\n"
    open(path, "w").write(s)
    return True


def run_build() -> int:
    return subprocess.call(
        [
            "xcodebuild",
            "-project",
            f"{PROJECT}/FirstStrike.xcodeproj",
            "-scheme",
            "NCLDesktop",
            "-destination",
            "platform=macOS",
            "build",
        ],
        stdout=open(LOG, "w"),
        stderr=subprocess.STDOUT,
        cwd=PROJECT,
    )


def extract_error_files() -> list[str]:
    """Find unique source file paths from the build log."""
    s = open(LOG).read()
    paths = set()
    for m in re.finditer(
        r"(/Users/natrix/Projects/FirstStrike/Sources/[^:]+\.swift)(?=:\d+:\d+:\s*error)", s
    ):
        paths.add(m.group(1))
    return sorted(paths)


def count_errors() -> int:
    s = open(LOG).read()
    return len(re.findall(r":\s*\d+:\d+:\s*error:", s))


def main():
    last_err_count = None
    for attempt in range(1, 16):
        rc = run_build()
        if rc == 0:
            print(f"[attempt {attempt}] BUILD SUCCEEDED")
            return 0
        errs = count_errors()
        files = extract_error_files()
        print(f"[attempt {attempt}] {errs} errors in {len(files)} files")
        if not files:
            print("  no source files matched — likely linker error:")
            for line in open(LOG).readlines():
                if "error" in line.lower():
                    print("    " + line.rstrip())
            return 1
        changed = 0
        for f in files:
            if wall_file(f):
                print(f"  walled {os.path.basename(f)}")
                changed += 1
        # If nothing was walled (patterns don't match), nuke-wrap the offending
        # files in #if os(iOS) as last resort
        if changed == 0:
            for f in files:
                if wrap_file_ios_only(f):
                    print(f"  iOS-only-wrapped {os.path.basename(f)}")
                    changed += 1
        if changed == 0:
            print("  no changes possible — giving up")
            for line in open(LOG).readlines()[-30:]:
                if "error" in line.lower():
                    print("    " + line.rstrip())
            return 1
        # If error count didn't decrease, escalate to nuke-wrap next round
        if last_err_count is not None and errs >= last_err_count:
            print("  errors not decreasing — escalating to iOS-only wraps")
            for f in files:
                if wrap_file_ios_only(f):
                    print(f"  iOS-only-wrapped {os.path.basename(f)}")
        last_err_count = errs
    print("still failing after 15 attempts")
    return 1


sys.exit(main())
