"""
Workspace MWP Stage Processor — Monitor and activate workspace pipelines

Manages the Managed Workspace Pipeline (MWP) stage processors for all 6 workspaces:
- execution-pipeline: Core mandate execution flow
- mandate-generation: Pump prompt synthesis into mandates
- intelligence-scan: Market/intelligence data ingestion
- feedback-synthesis: Execution feedback processing
- memory-processing: Long-term memory consolidation
- research-pipeline: Deep research and analysis

Each workspace has 5 numbered stages (01-NN through 05-NN) organized as:
- Direct stage directories with CONTEXT.md (execution-pipeline, intelligence-scan)
- Or stages/ subdirectory with CONTEXT.md in stage dirs (others)

Provides:
- WorkspaceProcessor: Manage individual workspace pipelines
- get_all_workspace_status(): Summary across all workspaces
- CLI: python3 -m runtime.mwp_processor --status

Usage:
    python3 -m runtime.mwp_processor --status  # Show all workspace status
    python3 -m runtime.mwp_processor --workspace execution-pipeline  # Single workspace
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Configuration ─────────────────────────────────────────────────────────

# NCL_BASE path: check env var first, then default to ~/dev/NCL
NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))

# Workspace definitions
WORKSPACES = {
    "execution-pipeline": ["01-Input", "02-Planning", "03-Execution", "04-Review", "05-Output"],
    "mandate-generation": ["01-intake", "02-analysis", "03-synthesis", "04-mandate-draft", "05-review"],
    "intelligence-scan": ["01-source-ingest", "02-signal-extraction", "03-importance-scoring", "04-insight-synthesis", "05-distribution"],
    "feedback-synthesis": ["01-report-intake", "02-validation", "03-pattern-detection", "04-recommendation", "05-mandate-update"],
    "memory-processing": ["01-episodic-intake", "02-semantic-extraction", "03-consolidation", "04-decay-reinforcement", "05-retrieval-indexing"],
    "research-pipeline": ["01-source-scan", "02-extraction", "03-analysis", "04-convergence", "05-archive"],
}

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("ncl.mwp")


# ── WorkspaceProcessor Class ───────────────────────────────────────────────

class WorkspaceProcessor:
    """Process and track status of a single workspace pipeline."""

    def __init__(self, workspace_name: str, ncl_base: Path = NCL_BASE):
        """
        Initialize workspace processor.

        Args:
            workspace_name: Name of workspace (execution-pipeline, etc.)
            ncl_base: Base path to NCL directory

        Raises:
            ValueError: If workspace_name is not in the known WORKSPACES dict
                        or contains path-traversal characters.
        """
        # Input validation: reject unknown workspace names and path-traversal attempts
        if workspace_name not in WORKSPACES:
            raise ValueError(
                f"Unknown workspace '{workspace_name}'. "
                f"Valid workspaces: {', '.join(sorted(WORKSPACES))}"
            )
        if ".." in workspace_name or "/" in workspace_name or "\\" in workspace_name:
            raise ValueError(f"Invalid workspace name '{workspace_name}': path traversal detected")

        # Validate ncl_base is a Path (not a bare string that could carry a traversal)
        ncl_base = Path(ncl_base).expanduser().resolve()

        self.name = workspace_name
        self.ncl_base = ncl_base
        self.workspace_dir = ncl_base / "workspaces" / workspace_name
        self.stages = WORKSPACES.get(workspace_name, [])

        # Determine if workspace uses stages/ subdirectory or direct structure
        self._use_stages_subdir = (self.workspace_dir / "stages").exists()

        # Shared state file path
        self.shared_dir = self.workspace_dir / "shared"
        self.state_file = self.shared_dir / f"{workspace_name}.json"

        log.debug(f"Initialized WorkspaceProcessor for {workspace_name}")

    def _get_stage_dir(self, stage_name: str) -> Path:
        """Get the actual directory for a stage."""
        if self._use_stages_subdir:
            return self.workspace_dir / "stages" / stage_name
        else:
            return self.workspace_dir / stage_name

    def _get_output_dir(self, stage_name: str) -> Path:
        """Get the output directory for a stage."""
        stage_dir = self._get_stage_dir(stage_name)
        output_dir = stage_dir / "output"
        if output_dir.exists():
            return output_dir
        # Fallback: check if stage dir itself contains artifacts
        return stage_dir

    def _read_context(self, stage_name: str) -> str:
        """Read CONTEXT.md for a stage."""
        stage_dir = self._get_stage_dir(stage_name)
        context_file = stage_dir / "CONTEXT.md"
        if context_file.exists():
            try:
                return context_file.read_text()
            except Exception as e:
                log.warning(f"Failed to read CONTEXT.md for {self.name}/{stage_name}: {e}")
        return ""

    def _count_artifacts(self, stage_name: str) -> int:
        """Count artifacts in a stage's output directory."""
        output_dir = self._get_output_dir(stage_name)
        if not output_dir.exists():
            return 0
        try:
            # Count all files (excluding .gitkeep and directories)
            return sum(1 for f in output_dir.rglob("*") if f.is_file() and f.name != ".gitkeep")
        except Exception as e:
            log.warning(f"Failed to count artifacts in {output_dir}: {e}")
            return 0

    def _get_last_processed(self, stage_name: str) -> str:
        """Get the last modification time of stage output."""
        output_dir = self._get_output_dir(stage_name)
        if not output_dir.exists():
            return ""
        try:
            # Find most recent file in output
            files = [f for f in output_dir.rglob("*") if f.is_file() and f.name != ".gitkeep"]
            if files:
                latest = max(files, key=lambda f: f.stat().st_mtime)
                mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
                return mtime.isoformat()
        except Exception as e:
            log.warning(f"Failed to get last processed time for {stage_name}: {e}")
        return ""

    def get_status(self) -> dict:
        """
        Get current status of all stages in this workspace.

        Returns:
            Dict with stage statuses and overall health
        """
        if not self.workspace_dir.exists():
            return {
                "workspace": self.name,
                "exists": False,
                "error": f"Workspace directory not found: {self.workspace_dir}",
            }

        stages_status = {}
        total_artifacts = 0

        for stage_name in self.stages:
            artifact_count = self._count_artifacts(stage_name)
            total_artifacts += artifact_count
            last_processed = self._get_last_processed(stage_name)

            stages_status[stage_name] = {
                "status": "active" if artifact_count > 0 else "idle",
                "artifacts": artifact_count,
                "last_processed": last_processed,
            }

        # Determine overall health
        health = "operational" if total_artifacts > 0 else "idle"
        active_stages = sum(1 for s in stages_status.values() if s["status"] == "active")

        state = {
            "workspace": self.name,
            "last_run": datetime.now(timezone.utc).isoformat(),
            "stages": stages_status,
            "total_artifacts": total_artifacts,
            "active_stages": active_stages,
            "health": health,
        }

        return state

    def update_state_file(self) -> None:
        """Update the shared state JSON file with current status."""
        try:
            self.shared_dir.mkdir(parents=True, exist_ok=True)
            state = self.get_status()
            self.state_file.write_text(json.dumps(state, indent=2))
            log.debug(f"Updated state file for {self.name}: {self.state_file}")
        except Exception as e:
            log.error(f"Failed to update state file for {self.name}: {e}")


# ── Global Status Functions ────────────────────────────────────────────────

def get_all_workspace_status(ncl_base: Path = NCL_BASE) -> dict:
    """
    Get status across all 6 workspaces.

    Returns:
        Dict with status for each workspace and summary stats
    """
    workspaces_status = {}
    total_all_artifacts = 0
    healthy_workspaces = 0

    for workspace_name in WORKSPACES.keys():
        processor = WorkspaceProcessor(workspace_name, ncl_base)
        status = processor.get_status()

        # Update state file if workspace exists
        if status.get("exists", True):  # exists=True is default for real workspaces
            processor.update_state_file()

        workspaces_status[workspace_name] = status

        # Accumulate stats
        if "total_artifacts" in status:
            total_all_artifacts += status["total_artifacts"]
            if status.get("health") == "operational":
                healthy_workspaces += 1

    # Overall pipeline health
    pipeline_health = "operational" if healthy_workspaces >= 4 else "degraded" if healthy_workspaces >= 2 else "offline"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ncl_base": str(ncl_base),
        "workspaces": workspaces_status,
        "summary": {
            "total_workspaces": len(WORKSPACES),
            "operational_workspaces": healthy_workspaces,
            "total_artifacts_across_all": total_all_artifacts,
            "pipeline_health": pipeline_health,
        },
    }


# ── CLI ────────────────────────────────────────────────────────────────────

def main() -> None:
    """Command-line interface for MWP processor."""
    parser = argparse.ArgumentParser(
        description="Workspace MWP Stage Processor",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show status of all workspaces (default)",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        metavar="NAME",
        help="Show status of specific workspace",
    )
    parser.add_argument(
        "--ncl-base",
        type=str,
        metavar="PATH",
        help="Override NCL_BASE path (default: env var or ~/dev/NCL)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON (default: pretty print)",
    )

    args = parser.parse_args()

    # Determine NCL_BASE
    ncl_base = Path(args.ncl_base) if args.ncl_base else NCL_BASE

    # Check if NCL_BASE exists
    if not ncl_base.exists():
        print(f"Error: NCL_BASE not found at {ncl_base}")
        if not args.ncl_base and not os.getenv("NCL_BASE"):
            print(f"Tip: Set NCL_BASE environment variable or use --ncl-base")
        return

    if args.workspace:
        # Single workspace status
        if args.workspace not in WORKSPACES:
            print(f"Error: Unknown workspace '{args.workspace}'")
            print(f"Available: {', '.join(WORKSPACES.keys())}")
            return

        processor = WorkspaceProcessor(args.workspace, ncl_base)
        status = processor.get_status()

        if args.json:
            print(json.dumps(status, indent=2))
        else:
            _print_workspace_status(status)

    else:
        # Default: show all workspaces
        all_status = get_all_workspace_status(ncl_base)

        if args.json:
            print(json.dumps(all_status, indent=2))
        else:
            _print_all_status(all_status)


def _print_workspace_status(status: dict) -> None:
    """Pretty-print single workspace status."""
    name = status.get("workspace", "unknown")
    print(f"\n{'=' * 70}")
    print(f"  {name.upper()}")
    print(f"{'=' * 70}")

    if "error" in status:
        print(f"ERROR: {status['error']}")
        return

    print(f"Health: {status.get('health', 'unknown').upper()}")
    print(f"Total Artifacts: {status.get('total_artifacts', 0)}")
    print(f"Last Updated: {status.get('last_run', 'N/A')}")
    print()

    stages = status.get("stages", {})
    for stage_name, stage_info in stages.items():
        artifacts = stage_info.get("artifacts", 0)
        stage_status = stage_info.get("status", "unknown")
        last_proc = stage_info.get("last_processed", "N/A")[:19]  # Truncate timestamp

        status_symbol = "✓" if stage_status == "active" else "○"
        print(f"  {status_symbol} {stage_name:30} {artifacts:3d} artifacts  [{last_proc}]")

    print()


def _print_all_status(all_status: dict) -> None:
    """Pretty-print all workspaces status."""
    summary = all_status.get("summary", {})
    print("\n" + "=" * 70)
    print("  MWP PIPELINE STATUS")
    print("=" * 70)
    print(f"Pipeline Health: {summary.get('pipeline_health', 'unknown').upper()}")
    print(f"Operational Workspaces: {summary.get('operational_workspaces', 0)}/{summary.get('total_workspaces', 0)}")
    print(f"Total Artifacts: {summary.get('total_artifacts_across_all', 0)}")
    print(f"Updated: {all_status.get('timestamp', 'N/A')}")
    print()

    workspaces = all_status.get("workspaces", {})
    for ws_name in sorted(WORKSPACES.keys()):
        ws_status = workspaces.get(ws_name, {})

        if "error" in ws_status:
            status_symbol = "✗"
            health_str = "ERROR"
        else:
            health = ws_status.get("health", "unknown")
            status_symbol = "✓" if health == "operational" else "○"
            health_str = health.upper()

        artifacts = ws_status.get("total_artifacts", 0)
        active_stages = ws_status.get("active_stages", 0)
        total_stages = len(WORKSPACES.get(ws_name, []))

        print(f"{status_symbol} {ws_name:30} {artifacts:3d} artifacts  {active_stages}/{total_stages} stages")

    print()


if __name__ == "__main__":
    main()
