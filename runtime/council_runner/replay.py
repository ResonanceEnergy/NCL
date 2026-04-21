"""Deterministic Replay Engine for Council Runner.

Saves runs to disk, loads historical records, and replays with comparison reports.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import CouncilRunRecord, ReplayConfig
from .agents import run_parallel_council

log = logging.getLogger("ncl.council_runner.replay")


class ReplayEngine:
    """Manages saving, loading, and replaying council runs."""

    def __init__(self, data_dir: str = "./data"):
        """Initialize replay engine with data directory."""
        self.data_dir = Path(data_dir)
        self.replays_dir = self.data_dir / "council_runner" / "replays"
        self.replays_dir.mkdir(parents=True, exist_ok=True)

    async def save_run(self, record: CouncilRunRecord) -> None:
        """Save a complete run record to JSON file."""
        run_file = self.replays_dir / f"{record.run_id}.json"

        # Serialize the record
        record_dict = record.model_dump(mode="json")

        async with await asyncio.to_thread(
            open, run_file, "w"
        ) as f:
            json.dump(record_dict, f, indent=2)

        log.info(f"Saved council run {record.run_id} to {run_file}")

    async def load_run(self, run_id: str) -> CouncilRunRecord:
        """Load a saved run record by ID."""
        run_file = self.replays_dir / f"{run_id}.json"

        if not run_file.exists():
            raise FileNotFoundError(f"No run found with ID {run_id}")

        with open(run_file) as f:
            data = json.load(f)

        return CouncilRunRecord(**data)

    async def replay(
        self,
        run_id: str,
        force_models: Optional[dict[str, str]] = None,
        temperature_override: Optional[float] = None,
    ) -> CouncilRunRecord:
        """
        Replay a council run with same prompt and seed.

        Optionally override models and/or temperature.
        Returns new record with replay provenance and diff report.
        """
        # Load original run
        original = await self.load_run(run_id)

        # Create replay config
        replay_config = ReplayConfig(
            run_id=run_id,
            replay_seed=original.replay_seed,
            force_models=force_models or {},
            temperature_override=temperature_override,
        )

        # Re-run the council
        new_record = await run_parallel_council(
            topic=original.topic,
            prompt=original.prompt,
            context=original.snapshot.get("context"),
            replay_config=replay_config,
        )

        # Generate diff report
        diff_report = self._compare_records(original, new_record)
        new_record.provenance["diff_report"] = diff_report

        log.info(f"Replayed council run {run_id}, new run ID: {new_record.run_id}")

        return new_record

    async def list_runs(self, limit: int = 50) -> list[dict]:
        """List summary of saved runs."""
        runs = []
        run_files = sorted(
            self.replays_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )

        for run_file in run_files[:limit]:
            try:
                with open(run_file) as f:
                    data = json.load(f)

                runs.append(
                    {
                        "run_id": data["run_id"],
                        "topic": data["topic"],
                        "timestamp": data["timestamp"],
                        "consensus_score": data.get("consensus", {}).get("consensus_score"),
                        "duration_ms": data.get("total_duration_ms"),
                    }
                )
            except (json.JSONDecodeError, KeyError):
                log.warning(f"Could not parse run file {run_file}")

        return runs

    async def compare_runs(self, run_id_a: str, run_id_b: str) -> dict:
        """Generate side-by-side comparison of two runs."""
        record_a = await self.load_run(run_id_a)
        record_b = await self.load_run(run_id_b)

        return self._compare_records(record_a, record_b)

    @staticmethod
    def _compare_records(record_a: CouncilRunRecord, record_b: CouncilRunRecord) -> dict:
        """Generate structured diff between two council run records."""
        return {
            "run_a_id": record_a.run_id,
            "run_b_id": record_b.run_id,
            "consensus_score_a": record_a.consensus.consensus_score if record_a.consensus else None,
            "consensus_score_b": record_b.consensus.consensus_score if record_b.consensus else None,
            "consensus_score_delta": (
                (record_b.consensus.consensus_score - record_a.consensus.consensus_score)
                if record_a.consensus and record_b.consensus
                else None
            ),
            "agreement_areas_changed": {
                "removed": [
                    a for a in (record_a.consensus.agreement_areas if record_a.consensus else [])
                    if a not in (record_b.consensus.agreement_areas if record_b.consensus else [])
                ],
                "added": [
                    a for a in (record_b.consensus.agreement_areas if record_b.consensus else [])
                    if a not in (record_a.consensus.agreement_areas if record_a.consensus else [])
                ],
            },
            "risk_flags_changed": {
                "removed": [
                    r for r in (record_a.consensus.risk_flags if record_a.consensus else [])
                    if r not in (record_b.consensus.risk_flags if record_b.consensus else [])
                ],
                "added": [
                    r for r in (record_b.consensus.risk_flags if record_b.consensus else [])
                    if r not in (record_a.consensus.risk_flags if record_a.consensus else [])
                ],
            },
            "duration_a_ms": record_a.total_duration_ms,
            "duration_b_ms": record_b.total_duration_ms,
            "duration_delta_ms": record_b.total_duration_ms - record_a.total_duration_ms,
        }

    @staticmethod
    def _generate_replay_seed(prompt: str, timestamp: Optional[str] = None) -> str:
        """Generate deterministic seed for replay."""
        import hashlib

        seed_input = f"{prompt}:{timestamp or ''}"
        return hashlib.sha256(seed_input.encode()).hexdigest()[:16]
