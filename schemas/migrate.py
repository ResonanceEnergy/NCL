#!/usr/bin/env python3
"""
NCL Schema Migration Tooling
Manages versioned schema migrations for event data, memory store, and config.
"""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATIONS_STATE_FILE = MIGRATIONS_DIR / ".migration_state.json"


def ensure_migrations_dir():
    MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)


def load_state():
    if MIGRATIONS_STATE_FILE.exists():
        return json.loads(MIGRATIONS_STATE_FILE.read_text(encoding="utf-8"))
    return {"applied": [], "last_run": None}


def save_state(state):
    state["last_run"] = datetime.now().isoformat()
    MIGRATIONS_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def list_migrations():
    """List all migration files in order."""
    ensure_migrations_dir()
    files = sorted(MIGRATIONS_DIR.glob("*.json"))
    return [f for f in files if not f.name.startswith(".")]


def create_migration(name: str, description: str, up_actions: list, down_actions: list | None = None):
    """Create a new versioned migration file."""
    ensure_migrations_dir()
    seq = len(list_migrations()) + 1
    filename = f"{seq:04d}_{name}.json"
    migration = {
        "version": seq,
        "name": name,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "up": up_actions,
        "down": down_actions or []
    }
    path = MIGRATIONS_DIR / filename
    path.write_text(json.dumps(migration, indent=2), encoding="utf-8")
    print(f"Created migration: {path}")
    return path


def apply_migration(migration_path: Path, state: dict):
    """Apply a single migration."""
    migration = json.loads(migration_path.read_text(encoding="utf-8"))
    name = migration["name"]
    version = migration["version"]

    if name in state["applied"]:
        print(f"  Skip (already applied): {name}")
        return False

    print(f"  Applying: {name} (v{version})")
    for action in migration.get("up", []):
        action_type = action.get("type")
        if action_type == "add_field":
            print(f"    + Add field: {action.get('path')}.{action.get('field')}")
        elif action_type == "rename_field":
            print(f"    ~ Rename: {action.get('old')} -> {action.get('new')}")
        elif action_type == "remove_field":
            print(f"    - Remove field: {action.get('path')}.{action.get('field')}")
        elif action_type == "update_schema_version":
            print(f"    * Schema version: {action.get('from')} -> {action.get('to')}")
        elif action_type == "backup":
            src = Path(os.path.expanduser(action.get("source", "")))
            if src.exists():
                backup = src.with_suffix(f".bak.{version}")
                shutil.copy2(src, backup)
                print(f"    Backup: {src} -> {backup}")
        else:
            print(f"    ? Unknown action: {action_type}")

    state["applied"].append(name)
    return True


def run_migrations(dry_run=False):
    """Apply all pending migrations in order."""
    state = load_state()
    migrations = list_migrations()
    pending = [m for m in migrations if m.stem.split("_", 1)[-1] not in state["applied"]
               and m.stem not in state["applied"]]

    if not pending:
        print("No pending migrations.")
        return 0

    print(f"Found {len(pending)} pending migration(s):")
    applied = 0
    for mig in pending:
        migration = json.loads(mig.read_text(encoding="utf-8"))
        name = migration["name"]
        if name in state["applied"]:
            continue
        if dry_run:
            print(f"  [DRY RUN] Would apply: {name}")
        else:
            if apply_migration(mig, state):
                applied += 1

    if not dry_run:
        save_state(state)
        print(f"Applied {applied} migration(s).")
    return applied


def status():
    """Show migration status."""
    state = load_state()
    migrations = list_migrations()
    print(f"Total migrations: {len(migrations)}")
    print(f"Applied: {len(state['applied'])}")
    print(f"Pending: {len(migrations) - len(state['applied'])}")
    print(f"Last run: {state.get('last_run', 'never')}")
    print()
    for mig in migrations:
        migration = json.loads(mig.read_text(encoding="utf-8"))
        name = migration["name"]
        mark = "✓" if name in state["applied"] else "○"
        print(f"  {mark} {mig.name}: {migration.get('description', '')}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="NCL Schema Migration Tool")
    sub = ap.add_subparsers(dest="command")

    sub.add_parser("status", help="Show migration status")
    sub.add_parser("run", help="Apply pending migrations")
    sub.add_parser("dry-run", help="Preview pending migrations without applying")

    create_p = sub.add_parser("create", help="Create a new migration")
    create_p.add_argument("name", help="Migration name (snake_case)")
    create_p.add_argument("--description", "-d", default="", help="Description")

    args = ap.parse_args()

    if args.command == "status":
        status()
    elif args.command == "run":
        run_migrations()
    elif args.command == "dry-run":
        run_migrations(dry_run=True)
    elif args.command == "create":
        create_migration(args.name, args.description, up_actions=[])
    else:
        ap.print_help()
