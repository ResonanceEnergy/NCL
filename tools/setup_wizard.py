#!/usr/bin/env python3
"""
NCL Setup Wizard — Interactive CLI onboarding for new installations.
Creates directory structure, validates dependencies, runs health checks,
and optionally starts the relay server.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

NCL_ROOT = Path(os.path.expanduser("~/NCL"))
REPO_ROOT = Path(__file__).parent.parent

REQUIRED_DIRS = [
    "data/event_log",
    "data/quarantine",
    "data/derived",
    "agents",
    "missions",
    "policies",
    "dist/reports/daily",
    "dist/reports/weekly",
    "dist/reports/drift",
    "dist/reports/overload",
    "audit",
    "memory",
]

REQUIRED_PYTHON_PACKAGES = [
    "jsonschema",
    "pytest",
]

OPTIONAL_PYTHON_PACKAGES = [
    ("fastapi", "HTTP API support"),
    ("uvicorn", "ASGI server"),
    ("requests", "HTTP client"),
    ("openai", "OpenAI backend for evaluation"),
    ("numpy", "Semantic vector search"),
]


def banner():
    print("""
    ╔══════════════════════════════════════════╗
    ║     NCL (NUREALCORTEXLINK) v3.0          ║
    ║     Setup Wizard                         ║
    ╚══════════════════════════════════════════╝
    """)


def prompt_yn(question: str, default: bool = True) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    answer = input(question + suffix).strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def step_create_dirs():
    print("\n[1/6] Creating directory structure...")
    for d in REQUIRED_DIRS:
        full = NCL_ROOT / d
        if full.exists():
            print(f"  OK  {full}")
        else:
            full.mkdir(parents=True, exist_ok=True)
            print(f"  NEW {full}")
    print(f"  Root: {NCL_ROOT}")


def step_check_python():
    print("\n[2/6] Checking Python environment...")
    ver = sys.version_info
    print(f"  Python {ver.major}.{ver.minor}.{ver.micro}")
    if ver.major < 3 or (ver.major == 3 and ver.minor < 9):
        print("  WARNING: Python 3.9+ recommended")
        return False
    print("  OK")
    return True


def step_install_deps(auto=False):
    print("\n[3/6] Checking dependencies...")
    missing = []
    for pkg in REQUIRED_PYTHON_PACKAGES:
        try:
            __import__(pkg)
            print(f"  OK  {pkg}")
        except ImportError:
            print(f"  MISSING {pkg}")
            missing.append(pkg)

    optional_missing = []
    for pkg, desc in OPTIONAL_PYTHON_PACKAGES:
        try:
            __import__(pkg)
            print(f"  OK  {pkg} ({desc})")
        except ImportError:
            print(f"  optional: {pkg} — {desc}")
            optional_missing.append(pkg)

    if missing:
        if auto or prompt_yn(f"Install {len(missing)} required package(s)?"):
            req_file = REPO_ROOT / "requirements-dev.txt"
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                          check=False)
        else:
            print("  Skipped. Run: pip install -r requirements-dev.txt")

    if optional_missing and not auto and prompt_yn(f"Install {len(optional_missing)} optional package(s)?", default=False):
        subprocess.run([sys.executable, "-m", "pip", "install", *optional_missing],
                      check=False)


def step_validate_config():
    print("\n[4/6] Validating configuration...")
    config_path = REPO_ROOT / "ncl_config.json"
    if not config_path.exists():
        print(f"  WARNING: {config_path} not found")
        return False

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        required_keys = ["system", "paths", "network", "schemas", "memory"]
        missing = [k for k in required_keys if k not in cfg]
        if missing:
            print(f"  WARNING: Missing config keys: {missing}")
            return False
        print(f"  System: {cfg['system'].get('name', '?')} v{cfg['system'].get('version', '?')}")
        print(f"  Relay port: {cfg['network'].get('relay_port', '?')}")
        print(f"  Local-only: {cfg['network'].get('local_only', '?')}")
        print("  OK")
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def step_validate_imports():
    print("\n[5/6] Validating import chain...")
    checks = [
        ("lib_ncl", "Core library shim"),
        ("ncl_memory", "Memory system"),
    ]
    all_ok = True
    for mod, desc in checks:
        try:
            __import__(mod)
            print(f"  OK  {mod} — {desc}")
        except Exception as e:
            print(f"  FAIL {mod} — {e}")
            all_ok = False

    # Check runtime modules
    runtime_mods = [
        "ncl_agency_runtime.runtime.relay_server",
        "ncl_agency_runtime.runtime.mission_runner",
    ]
    for mod in runtime_mods:
        try:
            parts = mod.split(".")
            # Just check the file exists
            mod_path = REPO_ROOT / "/".join(parts[:-1]) / (parts[-1] + ".py")
            if mod_path.exists():
                print(f"  OK  {mod}")
            else:
                print(f"  MISS {mod}")
                all_ok = False
        except Exception:
            pass

    return all_ok


def step_run_tests():
    print("\n[6/6] Running test suite...")
    test_dir = REPO_ROOT / "tests"
    if not test_dir.exists():
        print("  No tests directory found")
        return False

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_dir), "-v", "--tb=short", "-x", "-q"],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    if result.returncode == 0:
        # Count passes
        for line in result.stdout.split("\n"):
            if "passed" in line:
                print(f"  {line.strip()}")
        print("  OK")
        return True
    else:
        print("  Some tests failed:")
        for line in result.stdout.split("\n")[-10:]:
            if line.strip():
                print(f"  {line}")
        return False


def summary(results: dict):
    print("\n" + "=" * 50)
    print("  SETUP SUMMARY")
    print("=" * 50)
    all_ok = True
    for step_name, ok in results.items():
        status = "PASS" if ok else "WARN"
        if not ok:
            all_ok = False
        print(f"  [{status}] {step_name}")
    print()
    if all_ok:
        print("  NCL is ready! Start the relay server with:")
        print(f"    python {REPO_ROOT}/ncl_agency_runtime/runtime/relay_server.py")
        print()
        print("  Or run a daily brief mission:")
        print(f"    python {REPO_ROOT}/ncl_agency_runtime/runtime/mission_runner.py \\")
        print(f"      --mission {REPO_ROOT}/ncl_agency_runtime/missions/queue/daily_brief_today.json")
    else:
        print("  Some checks had warnings. NCL may still work, but review above.")
    print()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="NCL Setup Wizard")
    ap.add_argument("--auto", action="store_true", help="Non-interactive mode")
    ap.add_argument("--skip-tests", action="store_true", help="Skip test execution")
    args = ap.parse_args()

    # Ensure we're in the repo root for imports
    sys.path.insert(0, str(REPO_ROOT))

    banner()

    results = {}

    step_create_dirs()
    results["Directory structure"] = True

    results["Python version"] = step_check_python()
    step_install_deps(auto=args.auto)
    results["Dependencies"] = True  # best-effort

    results["Configuration"] = step_validate_config()
    results["Import chain"] = step_validate_imports()

    if not args.skip_tests:
        if args.auto or prompt_yn("Run test suite?"):
            results["Tests"] = step_run_tests()
        else:
            results["Tests"] = None
    else:
        results["Tests"] = None

    summary({k: v for k, v in results.items() if v is not None})


if __name__ == "__main__":
    main()
